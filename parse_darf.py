import re
import sys
from pathlib import Path
from datetime import datetime
from decimal import Decimal, InvalidOperation

import pdfplumber
import pandas as pd


# ==========================
# REGEX BÁSICOS E CONSTANTES
# ==========================

CNPJ_REGEX = re.compile(r"\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}")
DATA_REGEX = re.compile(r"\d{2}/\d{2}/\d{4}")
VALOR_REGEX = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2}")

# Linha digitável do DARF (bem específica, mas com alguma tolerância)
LINHA_DIGITAVEL_REGEX = re.compile(
    r"\b([89]\d{4}\d{7}\s\d\s\d{11}\s\d\s\d{11}\s\d\s\d{11}\s\d)\b"
)

# Configurações de OCR
TEXTO_MINIMO_PARA_VALIDO = 100
OCR_RESOLUCAO_DPI = 400


# ==========================
# FUNÇÕES DE VALIDAÇÃO
# ==========================

def normalizar_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos, mas preserva pra exibir formatado depois se quiser."""
    return re.sub(r"\D", "", cnpj or "")


def validar_cnpj(cnpj: str) -> bool:
    """
    Valida CNPJ com dígitos verificadores.
    Algoritmo padrão da Receita.
    """
    digits = normalizar_cnpj(cnpj)
    if len(digits) != 14:
        return False

    # descartar sequências repetidas (ex: 000000..., 111111..., etc.)
    if digits == digits[0] * 14:
        return False

    def calc_dv(digs, pesos):
        soma = sum(int(d) * p for d, p in zip(digs, pesos))
        r = soma % 11
        return "0" if r < 2 else str(11 - r)

    # primeiro DV
    dv1 = calc_dv(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    # segundo DV
    dv2 = calc_dv(digits[:12] + dv1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])

    return digits[-2:] == dv1 + dv2


def validar_data_br(data_str: str) -> bool:
    """Valida data no formato dd/mm/aaaa."""
    try:
        datetime.strptime(data_str, "%d/%m/%Y")
        return True
    except ValueError:
        return False


def validar_valor_br(valor_str: str) -> bool:
    """Valida se string parece um valor monetário brasileiro."""
    if not VALOR_REGEX.fullmatch(valor_str.strip()):
        return False
    try:
        # converte para Decimal só pra ver se faz sentido
        padrao = valor_str.replace(".", "").replace(",", ".")
        Decimal(padrao)
        return True
    except InvalidOperation:
        return False


# ==========================
# FUNÇÕES AUXILIARES
# ==========================

# Variável global para cache do reader OCR (lazy initialization)
_ocr_reader = None


def _obter_ocr_reader():
    """Inicializa e retorna o reader RapidOCR (singleton)."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            from rapidocr_onnxruntime import RapidOCR
            _ocr_reader = RapidOCR()
        except ImportError:
            _ocr_reader = False  # Marca como não disponível
    return _ocr_reader


def extrair_texto_com_ocr(imagem_pil):
    """
    Extrai texto de uma imagem usando RapidOCR.
    
    Args:
        imagem_pil: Imagem PIL (Pillow Image) ou numpy array
    
    Returns:
        Texto extraído e normalizado, ou string vazia se OCR falhar ou não estiver disponível.
    """
    reader = _obter_ocr_reader()
    if reader is False:
        return ""  # OCR não disponível
    
    try:
        # RapidOCR retorna lista de tuplas: [(bbox, text, confidence), ...]
        # O retorno pode ser uma tupla (result, elapsed_time) ou apenas a lista
        ocr_result = reader(imagem_pil)
        
        # Tratar diferentes formatos de retorno
        if isinstance(ocr_result, tuple):
            result = ocr_result[0]
        else:
            result = ocr_result
        
        if not result:
            return ""
        
        # Extrair textos e juntar
        # Cada item é uma tupla: (bbox, text, confidence)
        textos = []
        for item in result:
            if isinstance(item, (list, tuple)) and len(item) >= 2:
                texto = item[1]
                if texto:
                    textos.append(texto)
        
        if not textos:
            return ""
        
        texto_completo = "\n".join(textos)
        
        # Normalizar espaços
        texto_completo = re.sub(r"[ \t]+", " ", texto_completo)
        return texto_completo
    except Exception as e:
        # Log erro mas não quebra o pipeline
        print(f"Erro ao processar OCR: {e}", file=sys.stderr)
        return ""


def obter_total_paginas(pdf_path: Path) -> int:
    """Retorna o número total de páginas do PDF."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        return len(pdf.pages) if pdf.pages else 0


def carregar_texto_pdf(pdf_path: Path, numero_pagina: int = None):
    """
    Extrai o texto completo de uma página específica do PDF.
    Usa extração de texto nativo primeiro; se o texto extraído for insuficiente
    (< 100 caracteres), usa OCR como fallback para PDFs escaneados.
    
    Args:
        pdf_path: Caminho do arquivo PDF
        numero_pagina: Número da página (1-indexed). Se None, usa a primeira página.
    
    Returns:
        Texto completo da página normalizado (nativo ou extraído via OCR).
    """
    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            return ""
        
        if numero_pagina is None:
            idx_pagina = 0
        else:
            idx_pagina = numero_pagina - 1
            if idx_pagina < 0 or idx_pagina >= len(pdf.pages):
                return ""
        
        page = pdf.pages[idx_pagina]
        text = page.extract_text() or ""
        # Normaliza espaços múltiplos mas preserva quebras de linha
        text = re.sub(r"[ \t]+", " ", text)
        
        # Verificar se texto é insuficiente (após remover espaços)
        texto_sem_espacos = text.replace(" ", "").replace("\n", "")
        if len(texto_sem_espacos) < TEXTO_MINIMO_PARA_VALIDO:
            # Texto insuficiente, tentar OCR
            try:
                # Converter página para imagem
                imagem = page.to_image(resolution=OCR_RESOLUCAO_DPI)
                # Converter para PIL Image
                imagem_pil = imagem.original
                # Extrair texto com OCR
                texto_ocr = extrair_texto_com_ocr(imagem_pil)
                if texto_ocr:
                    # Normalizar espaços do texto OCR
                    texto_ocr = re.sub(r"[ \t]+", " ", texto_ocr)
                    return texto_ocr
            except Exception as e:
                # Se OCR falhar, retornar texto original (mesmo que insuficiente)
                print(f"Erro ao processar OCR para fallback: {e}", file=sys.stderr)
        
        return text


def carregar_linhas_pdf(pdf_path: Path, numero_pagina: int = None):
    """
    Extrai o texto de uma página específica do PDF e devolve como lista de linhas normalizadas.
    
    Args:
        pdf_path: Caminho do arquivo PDF
        numero_pagina: Número da página (1-indexed). Se None, usa a primeira página.
    
    Returns:
        Lista de linhas de texto normalizadas da página especificada.
    """
    text = carregar_texto_pdf(pdf_path, numero_pagina)
    
    # quebrar em linhas e normalizar espaços
    raw_lines = text.splitlines()
    lines = []
    for line in raw_lines:
        # remove espaços duplicados internos
        norm = re.sub(r"\s+", " ", line).strip()
        if norm:
            lines.append(norm)
    return lines


def encontrar_primeira_linha_com(lines, substring):
    """Retorna índice e conteúdo da primeira linha que contém a substring (case sensitive)."""
    for idx, line in enumerate(lines):
        if substring in line:
            return idx, line
    return None, None


# ==========================
# EXTRATORES DE CAMPOS
# ==========================

def extrair_cnpj_e_razao_social(lines, text=""):
    value = None
    erro = None
    razao = None
    erro_razao = None

    # Primeira tentativa: buscar nas linhas
    for idx, line in enumerate(lines):
        m = CNPJ_REGEX.search(line)
        if m:
            value = m.group(0)
            # tudo após o cnpj na mesma linha = razão social
            razao_candidato = line[m.end():].strip()
            
            # Remove caracteres especiais de tabela (|, ---, etc)
            razao_candidato = re.sub(r"^\||\|$|^---+", "", razao_candidato).strip()
            
            # Se encontrou algo, usa; senão tenta a próxima linha
            if razao_candidato:
                razao = razao_candidato
            else:
                # Tenta buscar na próxima linha se houver
                if idx + 1 < len(lines):
                    next_line = lines[idx + 1].strip()
                    # Remove caracteres de tabela
                    next_line = re.sub(r"^\||\|$|^---+", "", next_line).strip()
                    # Pula se for apenas números ou muito curta
                    if next_line and len(next_line) > 5 and not re.match(r"^[\d\s\.\-/]+$", next_line):
                        razao = next_line
            
            # Procura por "Razão Social" ou "Receita Social" como indicador
            if not razao or len(razao) < 5:
                for j in range(max(0, idx - 3), min(len(lines), idx + 5)):
                    if j != idx and ("Razão Social" in lines[j] or "Receita Social" in lines[j]):
                        # Tenta extrair o que vem depois do rótulo
                        partes = re.split(r"Razão Social|Receita Social", lines[j], flags=re.IGNORECASE)
                        if len(partes) > 1:
                            candidato = partes[1].strip()
                            candidato = re.sub(r"^\||\|$", "", candidato).strip()
                            if candidato and len(candidato) > 5:
                                razao = candidato
                                break
            break

    # Fallback: buscar no texto completo se não encontrou nas linhas
    if value is None and text:
        cnpj_match = CNPJ_REGEX.search(text)
        if cnpj_match:
            value = cnpj_match.group(0)
            # Tenta encontrar razão social próxima ao CNPJ no texto completo
            start = cnpj_match.end()
            end = min(len(text), start + 200)
            context = text[start:end]
            # Remove caracteres de tabela
            context = re.sub(r"\|+", " ", context)
            # Procura por texto que pareça razão social (maiúsculas, palavras)
            razao_match = re.search(r"([A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s]{10,})", context)
            if razao_match:
                razao = razao_match.group(1).strip()
                if len(razao) < 5 or len(razao) > 100:
                    razao = None

    if value is None:
        erro = "CNPJ não encontrado no texto."
    elif not validar_cnpj(value):
        erro = "CNPJ encontrado, porém inválido pelos dígitos verificadores."

    if not razao or len(razao) < 3:
        erro_razao = "Razão social não encontrada na linha do CNPJ."

    return value, erro, razao if razao and len(razao) >= 3 else None, erro_razao


def extrair_periodo_vencimento_numdoc(lines, text=""):
    periodo = None
    periodo_erro = None
    vencimento = None
    vencimento_erro = None
    num_doc = None
    num_doc_erro = None

    # Estratégia principal: achar linha de rótulo e pegar próxima
    idx, _ = encontrar_primeira_linha_com(lines, "Período de Apuração")
    if idx is not None:
        # Tenta na linha seguinte primeiro
        if idx + 1 < len(lines):
            valores_line = lines[idx + 1]
            # Ex: '30/09/2025 20/10/2025 07.01.25275.0746065-9'
            # Ou: '30/09/2025 | 20/10/2025 | 07.01.25275.0746065-9'
            m = re.search(
                r"(\d{2}/\d{2}/\d{4})\s*[|\s]+\s*(\d{2}/\d{2}/\d{4})\s*[|\s]+\s*([\d\.\-]+)",
                valores_line
            )
            if m:
                periodo = m.group(1)
                vencimento = m.group(2)
                num_doc = m.group(3)
        
        # Se não encontrou na linha seguinte, tenta na mesma linha
        if not periodo:
            linha_atual = lines[idx]
            m = re.search(
                r"(\d{2}/\d{2}/\d{4})\s*[|\s]+\s*(\d{2}/\d{2}/\d{4})\s*[|\s]+\s*([\d\.\-]+)",
                linha_atual
            )
            if m:
                periodo = m.group(1)
                vencimento = m.group(2)
                num_doc = m.group(3)
        
        # Se ainda não encontrou, procura nas próximas 3 linhas
        if not periodo:
            for offset in range(1, 4):
                if idx + offset < len(lines):
                    linha = lines[idx + offset]
                    # Procura por datas separadas
                    datas = DATA_REGEX.findall(linha)
                    if len(datas) >= 2:
                        periodo = datas[0]
                        vencimento = datas[1]
                        # Procura número do documento na mesma linha
                        num_match = re.search(r"([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", linha)
                        if num_match:
                            num_doc = num_match.group(1)
                        break

    # Fallback: buscar datas isoladamente
    if not periodo:
        for line in lines:
            if "Período de Apuração" in line:
                datas = DATA_REGEX.findall(line)
                if datas:
                    periodo = datas[0]
                    if len(datas) > 1:
                        vencimento = datas[1]
    
    if not vencimento:
        for line in lines:
            if "Data de Vencimento" in line or "Vencimento" in line:
                datas = DATA_REGEX.findall(line)
                if datas:
                    vencimento = datas[0]
                    break

    # Fallback para número do documento pela linha "Número:" ou padrão específico
    if num_doc is None:
        for line in lines:
            m = re.search(r"Número[:\s]+([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", line)
            if m:
                num_doc = m.group(1)
                break
            # Também procura o padrão diretamente
            m = re.search(r"([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", line)
            if m:
                num_doc = m.group(1)
                break

    # Fallback: buscar no texto completo se não encontrou tudo
    if (periodo is None or vencimento is None or num_doc is None) and text:
        # Normaliza espaços no texto para facilitar busca
        text_normalizado = re.sub(r"\s+", " ", text)
        
        # Busca períodos no texto completo - múltiplas estratégias
        if periodo is None:
            # Estratégia 1: Buscar próximo a "Período de Apuração"
            periodo_match = re.search(r"Período de Apuração[^:]*:?\s*(\d{2}/\d{2}/\d{4})", text_normalizado, re.IGNORECASE)
            if not periodo_match:
                # Estratégia 2: Buscar próximo a "Período"
                periodo_match = re.search(r"Período[^:]*:?\s*(\d{2}/\d{2}/\d{4})", text_normalizado, re.IGNORECASE)
            if not periodo_match:
                # Estratégia 3: Primeira data encontrada
                periodo_match = DATA_REGEX.search(text_normalizado)
            if periodo_match:
                periodo = periodo_match.group(1) if periodo_match.groups() else periodo_match.group(0)
        
        # Busca vencimento no texto completo - múltiplas estratégias
        if vencimento is None:
            # Estratégia 1: Buscar próximo a "Data de Vencimento"
            venc_match = re.search(r"Data de Vencimento[^:]*:?\s*(\d{2}/\d{2}/\d{4})", text_normalizado, re.IGNORECASE)
            if not venc_match:
                # Estratégia 2: Buscar próximo a "Vencimento"
                venc_match = re.search(r"Vencimento[^:]*:?\s*(\d{2}/\d{2}/\d{4})", text_normalizado, re.IGNORECASE)
            if not venc_match:
                # Estratégia 3: Buscar todas as datas e pegar a segunda ou última
                datas = DATA_REGEX.findall(text_normalizado)
                if len(datas) >= 2:
                    if periodo and datas[0] == periodo:
                        vencimento = datas[1]
                    else:
                        vencimento = datas[1] if len(datas) >= 2 else datas[-1]
                elif len(datas) == 1 and periodo and datas[0] != periodo:
                    vencimento = datas[0]
            elif venc_match:
                vencimento = venc_match.group(1) if venc_match.groups() else venc_match.group(0)
        
        # Busca número do documento no texto completo - múltiplas estratégias
        if num_doc is None:
            # Estratégia 1: Buscar próximo a "Número do Documento"
            num_match = re.search(r"Número do Documento[^:]*:?\s*([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", text_normalizado, re.IGNORECASE)
            if not num_match:
                # Estratégia 2: Buscar próximo a "Número"
                num_match = re.search(r"Número[^:]*:?\s*([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", text_normalizado, re.IGNORECASE)
            if not num_match:
                # Estratégia 3: Buscar padrão do número diretamente
                num_match = re.search(r"([\d]{2}\.[\d]{2}\.[\d]{5}\.[\d]{7}-[\d])", text_normalizado)
            if num_match:
                num_doc = num_match.group(1) if num_match.groups() else num_match.group(0)

    # Validar datas (após todos os fallbacks)
    if periodo is None:
        periodo_erro = "Período de apuração não encontrado."
    elif not validar_data_br(periodo):
        periodo_erro = "Período de apuração com formato inválido."

    if vencimento is None:
        vencimento_erro = "Data de vencimento não encontrada."
    elif not validar_data_br(vencimento):
        vencimento_erro = "Data de vencimento com formato inválido."

    if num_doc is None:
        num_doc_erro = "Número do documento não encontrado."

    return periodo, periodo_erro, vencimento, vencimento_erro, num_doc, num_doc_erro


def extrair_valor_total(lines, text=""):
    valor = None
    erro = None

    idx, _ = encontrar_primeira_linha_com(lines, "Valor Total do Documento")
    candidate_lines = []

    if idx is not None:
        # Verifica na mesma linha primeiro (pode estar em tabela)
        m = VALOR_REGEX.search(lines[idx])
        if m:
            valor = m.group(0)
            if validar_valor_br(valor):
                return valor, erro
        
        # pegar algumas linhas depois do rótulo
        for offset in range(1, 5):
            if idx + offset < len(lines):
                candidate_lines.append(lines[idx + offset])

    # procurar primeiro valor monetário nessas linhas
    for line in candidate_lines:
        # Remove caracteres de tabela antes de procurar
        line_limpa = re.sub(r"^\||\|$", "", line).strip()
        m = VALOR_REGEX.search(line_limpa)
        if m:
            valor_candidato = m.group(0)
            if validar_valor_br(valor_candidato):
                valor = valor_candidato
                break

    # Fallback: procurar "Valor:" na parte inferior
    if valor is None:
        for line in lines:
            if "Valor:" in line or "valor:" in line:
                m = VALOR_REGEX.search(line)
                if m:
                    valor_candidato = m.group(0)
                    if validar_valor_br(valor_candidato):
                        valor = valor_candidato
                        break

    # Fallback adicional: procurar valores grandes em qualquer lugar
    if valor is None:
        for line in lines:
            m = VALOR_REGEX.search(line)
            if m:
                valor_candidato = m.group(0)
                # Tenta validar e verificar se é um valor razoável (maior que 0)
                if validar_valor_br(valor_candidato):
                    # Remove formatação para comparar
                    valor_num = valor_candidato.replace(".", "").replace(",", ".")
                    try:
                        num_val = float(valor_num)
                        if num_val > 0:
                            valor = valor_candidato
                            break
                    except:
                        pass

    # Fallback: buscar no texto completo
    if valor is None and text:
        valor_match = re.search(r"Valor Total do Documento[^:]*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text, re.IGNORECASE)
        if not valor_match:
            valor_match = re.search(r"Valor[^:]*:?\s*(\d{1,3}(?:\.\d{3})*,\d{2})", text, re.IGNORECASE)
        if valor_match:
            valor_candidato = valor_match.group(1) if valor_match.groups() else valor_match.group(0)
            if validar_valor_br(valor_candidato):
                valor = valor_candidato

    if valor is None:
        erro = "Valor total do documento não encontrado."
    elif not validar_valor_br(valor):
        erro = "Valor total do documento com formato inválido."

    return valor, erro


def extrair_codigo_e_denom(lines, text=""):
    codigo = None
    codigo_erro = None
    denom = None
    denom_erro = None

    idx, _ = encontrar_primeira_linha_com(lines, "Composição do Documento de Arrecadação")
    if idx is not None:
        # Procura nas próximas 10 linhas após o título
        for j in range(idx + 1, min(idx + 11, len(lines))):
            line = lines[j]
            
            # Remove caracteres de tabela
            line_limpa = re.sub(r"^\||\|$", "", line).strip()
            
            # Procura código de 4 dígitos no início
            m = re.match(r"\s*(\d{4})\s+(.+)", line_limpa)
            if not m:
                # Tenta sem espaços no início
                m = re.match(r"(\d{4})\s+(.+)", line_limpa)
            
            if m:
                codigo = m.group(1)
                resto = m.group(2)
                
                # Remove caracteres de tabela do resto
                resto = re.sub(r"^\||\|$", "", resto).strip()
                
                # achar primeiro valor monetário no resto para separar
                vm = VALOR_REGEX.search(resto)
                if vm:
                    denom = resto[:vm.start()].strip()
                else:
                    denom = resto.strip()
                
                # Limpa a denominação de caracteres indesejados
                denom = re.sub(r"\s+", " ", denom).strip()
                
                # Se a denominação tem múltiplas linhas, tenta juntar
                if len(denom) < 10 and j + 1 < len(lines):
                    # Pode ser que a denominação continue na próxima linha
                    next_line = lines[j + 1].strip()
                    next_line = re.sub(r"^\||\|$", "", next_line).strip()
                    if next_line and not VALOR_REGEX.search(next_line) and not re.match(r"^\d+$", next_line):
                        denom = (denom + " " + next_line).strip()
                
                break

    # Fallback: buscar no texto completo
    if codigo is None and text:
        codigo_match = re.search(r"Composição[^:]*?:[^:]*?(\d{4})\s+([A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s]{10,})", text, re.IGNORECASE | re.DOTALL)
        if codigo_match:
            codigo = codigo_match.group(1)
            if not denom or len(denom.strip()) < 3:
                denom_candidato = codigo_match.group(2).strip()[:200]  # Limita tamanho
                denom = re.sub(r"\s+", " ", denom_candidato).strip()

    if codigo is None:
        codigo_erro = "Código não encontrado na composição do documento."
    if not denom or len(denom.strip()) < 3:
        denom_erro = "Denominação não encontrada ou vazia."

    return codigo, codigo_erro, denom if denom and len(denom.strip()) >= 3 else None, denom_erro


def extrair_linha_digitavel(lines, text=""):
    linha = None
    erro = None

    # procurar linha inteira que satisfaça regex mais forte
    for line in lines:
        m = LINHA_DIGITAVEL_REGEX.search(line)
        if m:
            linha = m.group(1)
            break

    # fallback mais permissivo: linha começando com 8 ou 9 com muitos dígitos
    if linha is None:
        for line in lines:
            if re.match(r"^[89]\d{4}", line) and len(re.sub(r"\D", "", line)) >= 40:
                linha = line.strip()
                break

    # Fallback: buscar no texto completo
    if linha is None and text:
        # Procura padrão de linha digitável no texto completo (pode estar fragmentado)
        linha_match = LINHA_DIGITAVEL_REGEX.search(text)
        if linha_match:
            linha = linha_match.group(1)
        else:
            # Tenta encontrar números que formam a linha digitável mesmo fragmentados
            numeros = re.findall(r"\d+", text)
            # Junta números grandes que podem formar a linha digitável
            linha_candidato = " ".join([n for n in numeros if len(n) >= 10])[:60]
            if len(re.sub(r"\D", "", linha_candidato)) >= 44:
                linha = linha_candidato

    if linha is None:
        erro = "Linha digitável não encontrada."
    return linha, erro


# ==========================
# PIPELINE PRINCIPAL
# ==========================

def processar_pdf_pagina(pdf_path: Path, numero_pagina: int) -> dict:
    """
    Processa uma página específica de um DARF em PDF e retorna um dicionário com
    campos + mensagens de erro por campo.
    
    Args:
        pdf_path: Caminho do arquivo PDF
        numero_pagina: Número da página a processar (1-indexed)
    
    Returns:
        Dicionário com os campos extraídos e nome de arquivo formatado com número da página.
    """
    nome_arquivo = pdf_path.name
    resultado = {
        "arquivo": f"{nome_arquivo} - Página {numero_pagina}",
        "cnpj": None,
        "cnpj_erro": None,
        "razao_social": None,
        "razao_social_erro": None,
        "periodo_apuracao": None,
        "periodo_apuracao_erro": None,
        "data_vencimento": None,
        "data_vencimento_erro": None,
        "numero_documento": None,
        "numero_documento_erro": None,
        "valor_total_documento": None,
        "valor_total_documento_erro": None,
        "codigo": None,
        "codigo_erro": None,
        "denominacao": None,
        "denominacao_erro": None,
        "linha_digitavel": None,
        "linha_digitavel_erro": None,
    }

    lines = carregar_linhas_pdf(pdf_path, numero_pagina)
    text = carregar_texto_pdf(pdf_path, numero_pagina)

    # CNPJ + Razão Social
    cnpj, cnpj_erro, razao, razao_erro = extrair_cnpj_e_razao_social(lines, text)
    resultado["cnpj"] = cnpj
    resultado["cnpj_erro"] = cnpj_erro
    resultado["razao_social"] = razao
    resultado["razao_social_erro"] = razao_erro

    # Período, Vencimento, Número do Documento
    (periodo, periodo_erro,
     venc, venc_erro,
     num_doc, num_doc_erro) = extrair_periodo_vencimento_numdoc(lines, text)
    resultado["periodo_apuracao"] = periodo
    resultado["periodo_apuracao_erro"] = periodo_erro
    resultado["data_vencimento"] = venc
    resultado["data_vencimento_erro"] = venc_erro
    resultado["numero_documento"] = num_doc
    resultado["numero_documento_erro"] = num_doc_erro

    # Valor Total
    valor_total, valor_erro = extrair_valor_total(lines, text)
    resultado["valor_total_documento"] = valor_total
    resultado["valor_total_documento_erro"] = valor_erro

    # Código + Denominação
    codigo, codigo_erro, denom, denom_erro = extrair_codigo_e_denom(lines, text)
    resultado["codigo"] = codigo
    resultado["codigo_erro"] = codigo_erro
    resultado["denominacao"] = denom
    resultado["denominacao_erro"] = denom_erro

    # Linha digitável
    linha, linha_erro = extrair_linha_digitavel(lines, text)
    resultado["linha_digitavel"] = linha
    resultado["linha_digitavel_erro"] = linha_erro

    return resultado


def processar_pdf(pdf_path: Path) -> list[dict]:
    """
    Processa todas as páginas de um DARF em PDF e retorna uma lista de dicionários,
    um para cada página, com campos + mensagens de erro por campo.
    
    Args:
        pdf_path: Caminho do arquivo PDF
    
    Returns:
        Lista de dicionários, onde cada dicionário contém os campos extraídos de uma página.
        Cada dicionário tem o campo "arquivo" formatado como "nome.pdf - Página X".
    """
    total_paginas = obter_total_paginas(pdf_path)
    
    if total_paginas == 0:
        # PDF vazio ou inválido - retorna uma entrada de erro
        nome_arquivo = pdf_path.name
        return [{
            "arquivo": f"{nome_arquivo} - Página 1",
            "cnpj": None,
            "cnpj_erro": "PDF vazio ou inválido.",
            "razao_social": None,
            "razao_social_erro": "PDF vazio ou inválido.",
            "periodo_apuracao": None,
            "periodo_apuracao_erro": "PDF vazio ou inválido.",
            "data_vencimento": None,
            "data_vencimento_erro": "PDF vazio ou inválido.",
            "numero_documento": None,
            "numero_documento_erro": "PDF vazio ou inválido.",
            "valor_total_documento": None,
            "valor_total_documento_erro": "PDF vazio ou inválido.",
            "codigo": None,
            "codigo_erro": "PDF vazio ou inválido.",
            "denominacao": None,
            "denominacao_erro": "PDF vazio ou inválido.",
            "linha_digitavel": None,
            "linha_digitavel_erro": "PDF vazio ou inválido.",
        }]
    
    resultados = []
    for numero_pagina in range(1, total_paginas + 1):
        resultado = processar_pdf_pagina(pdf_path, numero_pagina)
        resultados.append(resultado)
    
    return resultados


def processar_pasta(pasta_pdf: Path, output_csv: Path, output_xlsx: Path):
    pdf_files = sorted(pasta_pdf.glob("*.pdf"))
    if not pdf_files:
        print(f"Nenhum PDF encontrado em: {pasta_pdf}")
        return

    registros = []
    for pdf in pdf_files:
        print(f"Processando: {pdf.name}")
        try:
            # processar_pdf agora retorna uma lista de resultados (um por página)
            resultados_paginas = processar_pdf(pdf)
            registros.extend(resultados_paginas)
        except Exception as e:
            # em caso de erro geral, registra linha com erro genérico (pelo menos uma página)
            nome_arquivo = pdf.name
            registros.append({
                "arquivo": f"{nome_arquivo} - Página 1",
                "cnpj": None,
                "cnpj_erro": f"Erro geral ao processar PDF: {e}",
                "razao_social": None,
                "razao_social_erro": f"Erro geral ao processar PDF: {e}",
                "periodo_apuracao": None,
                "periodo_apuracao_erro": f"Erro geral ao processar PDF: {e}",
                "data_vencimento": None,
                "data_vencimento_erro": f"Erro geral ao processar PDF: {e}",
                "numero_documento": None,
                "numero_documento_erro": f"Erro geral ao processar PDF: {e}",
                "valor_total_documento": None,
                "valor_total_documento_erro": f"Erro geral ao processar PDF: {e}",
                "codigo": None,
                "codigo_erro": f"Erro geral ao processar PDF: {e}",
                "denominacao": None,
                "denominacao_erro": f"Erro geral ao processar PDF: {e}",
                "linha_digitavel": None,
                "linha_digitavel_erro": f"Erro geral ao processar PDF: {e}",
            })

    df = pd.DataFrame(registros)

    # salva CSV
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    # salva XLSX
    df.to_excel(output_xlsx, index=False)

    print(f"\nArquivos gerados:")
    print(f"  - CSV : {output_csv}")
    print(f"  - XLSX: {output_xlsx}")


def main():
    if len(sys.argv) < 2:
        print("Uso: python parse_darf.py CAMINHO_PASTA_PDFS")
        sys.exit(1)

    pasta = Path(sys.argv[1]).expanduser().resolve()
    if not pasta.is_dir():
        print(f"Pasta não encontrada: {pasta}")
        sys.exit(1)

    output_csv = pasta / "resultado_darfs.csv"
    output_xlsx = pasta / "resultado_darfs.xlsx"

    processar_pasta(pasta, output_csv, output_xlsx)


if __name__ == "__main__":
    main()