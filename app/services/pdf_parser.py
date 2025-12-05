import re
import sys
from pathlib import Path
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Optional

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

    # Busca mais flexível por "Composição" (pode estar fragmentado no OCR)
    idx = None
    for i, line in enumerate(lines):
        # Busca case-insensitive e tolerante a fragmentação
        if "composição" in line.lower() and "arrecadação" in line.lower():
            idx = i
            break
        # Fallback: só "Composição" pode ser suficiente
        if idx is None and "composição" in line.lower():
            idx = i
    
    if idx is not None:
        # Procura nas próximas 15 linhas após o título (aumentado para capturar denominações longas)
        for j in range(idx + 1, min(idx + 16, len(lines))):
            line = lines[j]
            
            # Remove TODOS os caracteres de tabela (|) da linha, não só do início/fim
            line_limpa = re.sub(r"\|+", " ", line).strip()
            
            # Procura código de 4 dígitos no início da linha (pode ter espaços antes)
            # Aceita código seguido de espaço e depois qualquer coisa
            # IMPORTANTE: Evita capturar anos de datas (não deve estar em formato de data)
            m = re.search(r"(\d{4})\s+(.+)", line_limpa)
            
            if m:
                codigo_candidato = m.group(1)
                resto = m.group(2)
                
                # Validação: não deve ser um ano de data (evita 2025, 2024, etc.)
                # Aplica validação mais rigorosa apenas para códigos que podem ser anos
                if (codigo_candidato.startswith("20") or codigo_candidato.startswith("19")):
                    # Pode ser um ano, verifica se está em contexto de data
                    # Se o resto começa com números ou "/", provavelmente é uma data
                    if re.match(r"^[\d\s/]+", resto.strip()):
                        continue  # Pula este match, provavelmente é uma data
                    # Para anos, também verifica se está seguido de texto que parece denominação
                    # Se não começa com maiúscula, provavelmente é um ano
                    if not re.match(r"^[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]", resto.strip()):
                        continue  # Pula se não começa com maiúscula (provavelmente é ano)
                
                # Remove espaços extras
                resto = re.sub(r"\s+", " ", resto).strip()
                
                # Achar primeiro valor monetário no resto para separar a denominação
                vm = VALOR_REGEX.search(resto)
                if vm:
                    denom_candidato = resto[:vm.start()].strip()
                else:
                    denom_candidato = resto.strip()
                
                # Se encontrou código, tenta juntar linhas seguintes para a denominação
                if codigo_candidato:
                    codigo = codigo_candidato
                    partes_denom = [denom_candidato] if denom_candidato else []
                    
                    # Junta linhas seguintes que parecem ser continuação da denominação
                    # Para até encontrar um valor monetário ou linha que claramente não é denominação
                    for k in range(j + 1, min(j + 6, len(lines))):
                        next_line = lines[k]
                        next_line_limpa = re.sub(r"\|+", " ", next_line).strip()
                        
                        # Para se encontrar um valor monetário (fim da denominação)
                        if VALOR_REGEX.search(next_line_limpa):
                            break
                        
                        # Para se for uma linha que claramente não é denominação
                        # (ex: "Totais", números sozinhos, etc)
                        if (re.match(r"^(Totais|Total)$", next_line_limpa, re.IGNORECASE) or
                            re.match(r"^\d+$", next_line_limpa) or
                            len(next_line_limpa) < 3):
                            break
                        
                        # Se a linha tem texto que parece denominação, adiciona
                        if next_line_limpa and not re.match(r"^[\d\s\.\-/]+$", next_line_limpa):
                            # Remove padrões como "PA 09/2025 Vencimento 20/10/2025" se aparecer
                            if not re.search(r"PA\s+\d{2}/\d{4}", next_line_limpa, re.IGNORECASE):
                                partes_denom.append(next_line_limpa)
                    
                    # Junta todas as partes da denominação
                    if partes_denom:
                        denom = " ".join(partes_denom)
                        denom = re.sub(r"\s+", " ", denom).strip()
                    
                    break
    
    # Busca alternativa nas linhas: procura código de 4 dígitos diretamente
    # Útil quando "Composição" não é encontrado ou está fragmentado
    # Estratégia: procura código seguido de denominação OU código isolado próximo a valor monetário
    if codigo is None:
        for j, line in enumerate(lines):
            # Remove caracteres de tabela
            line_limpa = re.sub(r"\|+", " ", line).strip()
            
            # Estratégia 1: Código seguido de texto que parece denominação
            m = re.search(r"(\d{4})\s+([A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s\-\d/]{5,})", line_limpa)
            if m:
                codigo_candidato = m.group(1)
                # Validação: evita capturar anos de datas (2025, 2024, etc.)
                if codigo_candidato.startswith("20") or codigo_candidato.startswith("19"):
                    # Verifica se está próximo a padrões de data (com "/")
                    linha_antes = lines[j-1] if j > 0 else ""
                    linha_depois = lines[j+1] if j+1 < len(lines) else ""
                    contexto = f"{linha_antes} {line_limpa} {linha_depois}"
                    # Se há padrão de data próximo (dd/mm/aaaa ou aaaa), provavelmente é ano
                    if re.search(r"\d{2}/\d{2}/" + codigo_candidato, contexto) or re.search(codigo_candidato + r"\s*$", linha_antes):
                        continue  # Pula, provavelmente é um ano de data
                # Verifica se há um valor monetário próximo (dentro de algumas linhas)
                # Isso confirma que é realmente o código da composição
                for k in range(max(0, j - 2), min(len(lines), j + 5)):
                    if VALOR_REGEX.search(lines[k]):
                        codigo = codigo_candidato
                        # Extrai denominação da mesma linha ou linhas seguintes
                        resto = m.group(2)
                        # Remove valor monetário se estiver no resto
                        vm = VALOR_REGEX.search(resto)
                        if vm:
                            denom_candidato = resto[:vm.start()].strip()
                        else:
                            denom_candidato = resto.strip()
                        
                        # Junta linhas seguintes se necessário
                        partes_denom = [denom_candidato] if denom_candidato else []
                        for k in range(j + 1, min(j + 6, len(lines))):
                            next_line = lines[k]
                            next_line_limpa = re.sub(r"\|+", " ", next_line).strip()
                            
                            if VALOR_REGEX.search(next_line_limpa):
                                break
                            
                            if (re.match(r"^(Totais|Total)$", next_line_limpa, re.IGNORECASE) or
                                re.match(r"^\d+$", next_line_limpa) or
                                len(next_line_limpa) < 3):
                                break
                            
                            if next_line_limpa and not re.match(r"^[\d\s\.\-/]+$", next_line_limpa):
                                if not re.search(r"PA\s+\d{2}/\d{4}", next_line_limpa, re.IGNORECASE):
                                    partes_denom.append(next_line_limpa)
                        
                        if partes_denom:
                            denom = " ".join(partes_denom)
                            denom = re.sub(r"\s+", " ", denom).strip()
                        break
                if codigo:
                    break
            
            # Estratégia 2: Código isolado (pode estar em linha separada no OCR)
            # Procura código de 4 dígitos sozinho ou com pouco texto, mas próximo a valor monetário
            if codigo is None:
                # Procura código de 4 dígitos que não seja ano
                m = re.search(r"^(\d{4})\s*$|^\s*(\d{4})\s+(.{0,20})$", line_limpa)
                if m:
                    codigo_candidato = m.group(1) or m.group(2)
                    # Ignora anos (2025, 2024, etc.) - apenas se não começar com 20 ou 19
                    if codigo_candidato and not (codigo_candidato.startswith("20") or codigo_candidato.startswith("19")):
                        # Verifica se há valor monetário nas próximas 5 linhas
                        for k in range(j + 1, min(j + 6, len(lines))):
                            if VALOR_REGEX.search(lines[k]):
                                # Verifica se há texto que parece denominação entre o código e o valor
                                # ou nas linhas anteriores
                                tem_denom = False
                                for l in range(max(0, j - 2), k):
                                    linha_check = re.sub(r"\|+", " ", lines[l]).strip()
                                    if re.search(r"[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]{5,}", linha_check):
                                        tem_denom = True
                                        break
                                
                                if tem_denom or j < k - 1:  # Se há espaço para denominação
                                    codigo = codigo_candidato
                                    # Tenta extrair denominação das linhas entre código e valor
                                    partes_denom = []
                                    for l in range(j + 1, k):
                                        linha_denom = re.sub(r"\|+", " ", lines[l]).strip()
                                        if linha_denom and not VALOR_REGEX.search(linha_denom):
                                            if not re.match(r"^(Totais|Total|\d+)$", linha_denom, re.IGNORECASE):
                                                if re.search(r"[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]", linha_denom):
                                                    partes_denom.append(linha_denom)
                                    
                                    if partes_denom:
                                        denom = " ".join(partes_denom)
                                        denom = re.sub(r"\s+", " ", denom).strip()
                                    break
                        if codigo:
                            break

    # Fallback: buscar no texto completo se não encontrou nas linhas
    if codigo is None and text:
        # Normaliza espaços no texto (mas preserva estrutura básica)
        text_normalizado = re.sub(r"\s+", " ", text)
        
        # Estratégia 1: Busca código próximo a "Composição" (mais flexível)
        # Procura "Composição" seguido de qualquer coisa e depois um código de 4 dígitos
        # IMPORTANTE: Evita capturar anos de datas
        composicao_match = re.search(r"composição[^:]*?:?[^:]*?(\d{4})", text_normalizado, re.IGNORECASE)
        if composicao_match:
            codigo_candidato = composicao_match.group(1)
            # Validação: não deve ser um ano (2025, 2024, etc.)
            # Verifica o contexto após o código
            pos_codigo = composicao_match.end()
            contexto_apos = text_normalizado[pos_codigo:pos_codigo + 50]
            # Se o código começa com 20 ou 19 e está seguido de padrão de data, é ano
            if (codigo_candidato.startswith("20") or codigo_candidato.startswith("19")):
                if re.match(r"^\s*[/\d\s]", contexto_apos):
                    codigo_candidato = None  # Provavelmente é ano
                elif not re.match(r"^\s+[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]", contexto_apos):
                    codigo_candidato = None  # Não parece estar seguido de denominação
            if codigo_candidato:
                codigo = codigo_candidato
        else:
            # Estratégia 2: Busca qualquer código de 4 dígitos após palavras-chave relacionadas
            # Procura por padrões como "Código 1082" ou "1082" próximo a "Denominação"
            codigo_match = re.search(r"(?:código|denominação)[^:]*?:?[^:]*?(\d{4})", text_normalizado, re.IGNORECASE)
            if codigo_match:
                codigo = codigo_match.group(1)
            else:
                # Estratégia 3: Busca código de 4 dígitos isolado que aparece após "Composição"
                # Procura "Composição" e depois o primeiro código de 4 dígitos encontrado
                # IMPORTANTE: Filtra anos de datas
                composicao_pos = text_normalizado.lower().find("composição")
                if composicao_pos >= 0:
                    # Procura código de 4 dígitos nos próximos 500 caracteres
                    contexto_apos = text_normalizado[composicao_pos:composicao_pos + 500]
                    # Busca todos os códigos de 4 dígitos e filtra os que são anos
                    todos_codigos = re.finditer(r"(\d{4})", contexto_apos)
                    for codigo_match in todos_codigos:
                        codigo_candidato = codigo_match.group(1)
                        # Verifica se não é um ano de data
                        if codigo_candidato.startswith("20") or codigo_candidato.startswith("19"):
                            # Verifica contexto: se está em formato de data, pula
                            start = codigo_match.start()
                            end = codigo_match.end()
                            antes = contexto_apos[max(0, start-10):start]
                            depois = contexto_apos[end:min(len(contexto_apos), end+10)]
                            # Se há "/" antes ou depois, provavelmente é data
                            if "/" in antes or "/" in depois:
                                continue
                            # Se não está seguido de texto que parece denominação, pula
                            if not re.match(r"^\s+[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]", depois):
                                continue
                        # Se passou nas validações, usa este código
                        codigo = codigo_candidato
                        break
        
        # Se encontrou código, tenta encontrar denominação
        if codigo:
            # Encontra a posição do código no texto
            codigo_pos = text_normalizado.find(codigo)
            if codigo_pos >= 0:
                # Procura denominação após o código (até 400 caracteres)
                context = text_normalizado[codigo_pos + len(codigo):codigo_pos + len(codigo) + 400]
                
                # Remove caracteres de tabela e normaliza
                context = re.sub(r"\|+", " ", context)
                context = re.sub(r"\s+", " ", context)
                
                # Procura denominação: texto em maiúsculas que não seja só números
                # Aceita texto que começa com letras maiúsculas e contém palavras
                # Para quando encontra um valor monetário ou "Totais"
                denom_match = re.search(
                    r"([A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s\-\d/]{5,}?)(?=\d{1,3}(?:\.\d{3})*,\d{2}|Totais|Total|$)",
                    context,
                    re.IGNORECASE
                )
                if denom_match:
                    denom_candidato = denom_match.group(1).strip()
                    # Remove padrões comuns que não são parte da denominação
                    # Remove "PA 09/2025 Vencimento 20/10/2025" se aparecer no final
                    denom_candidato = re.sub(r"\s*PA\s+\d{2}/\d{4}\s+Vencimento\s+\d{2}/\d{4}.*$", "", denom_candidato, flags=re.IGNORECASE)
                    # Limita tamanho e limpa
                    denom = re.sub(r"\s+", " ", denom_candidato[:250]).strip()

    # Último fallback: busca direta por código de 4 dígitos próximo a valores monetários
    # Isso funciona mesmo quando "Composição" não é encontrado
    if codigo is None and text:
        text_normalizado = re.sub(r"\s+", " ", text)
        
        # Estratégia 1: Padrão completo código + denominação + valor
        padrao_codigo_valor = re.search(
            r"(\d{4})\s+([A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ][A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ\s\-\d/]{10,}?)\s+(\d{1,3}(?:\.\d{3})*,\d{2})",
            text_normalizado,
            re.IGNORECASE
        )
        if padrao_codigo_valor:
            codigo_candidato = padrao_codigo_valor.group(1)
            # Validação: evita capturar anos (2025, 2024, etc.)
            if codigo_candidato.startswith("20") or codigo_candidato.startswith("19"):
                pos_codigo = padrao_codigo_valor.start(1)
                contexto_antes = text_normalizado[max(0, pos_codigo-20):pos_codigo]
                if re.search(r"\d{2}/\d{2}/$", contexto_antes):
                    codigo_candidato = None
            if codigo_candidato:
                codigo = codigo_candidato
                if not denom:
                    denom_candidato = padrao_codigo_valor.group(2).strip()
                    denom_candidato = re.sub(r"\s*PA\s+\d{2}/\d{4}\s+Vencimento\s+\d{2}/\d{4}.*$", "", denom_candidato, flags=re.IGNORECASE)
                    denom = re.sub(r"\s+", " ", denom_candidato[:250]).strip()
        
        # Estratégia 2: Busca todos os códigos de 4 dígitos e valores monetários
        # Encontra o código que está mais próximo de um valor monetário (dentro de 200 caracteres)
        if codigo is None:
            # Encontra todos os valores monetários
            valores = list(re.finditer(r"(\d{1,3}(?:\.\d{3})*,\d{2})", text_normalizado))
            # Encontra todos os códigos de 4 dígitos
            todos_codigos = list(re.finditer(r"(\d{4})", text_normalizado))
            
            melhor_codigo = None
            melhor_distancia = float('inf')
            
            for codigo_match in todos_codigos:
                codigo_candidato = codigo_match.group(1)
                # Ignora anos (2025, 2024, etc.)
                if codigo_candidato.startswith("20") or codigo_candidato.startswith("19"):
                    # Verifica contexto
                    start = codigo_match.start()
                    antes = text_normalizado[max(0, start-10):start]
                    depois = text_normalizado[codigo_match.end():min(len(text_normalizado), codigo_match.end()+10)]
                    if "/" in antes or "/" in depois:
                        continue  # Provavelmente é ano
                
                # Procura valor monetário mais próximo após o código
                codigo_pos = codigo_match.end()
                for valor_match in valores:
                    valor_pos = valor_match.start()
                    if valor_pos > codigo_pos:  # Valor está após o código
                        distancia = valor_pos - codigo_pos
                        # Se está dentro de 200 caracteres e é a menor distância até agora
                        if distancia < 200 and distancia < melhor_distancia:
                            # Verifica se há texto entre código e valor (denominação)
                            texto_entre = text_normalizado[codigo_pos:valor_pos]
                            if re.search(r"[A-ZÁÀÂÃÉÈÊÍÌÎÓÒÔÕÚÙÛÇ]{3,}", texto_entre):
                                melhor_codigo = codigo_candidato
                                melhor_distancia = distancia
                                # Extrai denominação do texto entre código e valor
                                if not denom:
                                    denom_candidato = texto_entre.strip()
                                    denom_candidato = re.sub(r"\s*PA\s+\d{2}/\d{4}\s+Vencimento\s+\d{2}/\d{4}.*$", "", denom_candidato, flags=re.IGNORECASE)
                                    denom = re.sub(r"\s+", " ", denom_candidato[:250]).strip()
                                break
            
            if melhor_codigo:
                codigo = melhor_codigo

    if codigo is None:
        codigo_erro = "Código não encontrado na composição do documento."
    if not denom or len(denom.strip()) < 3:
        denom_erro = "Denominação não encontrada ou vazia."

    return codigo, codigo_erro, denom if denom and len(denom.strip()) >= 3 else None, denom_erro


def calcular_score_linha_digitavel(digitos: str) -> int:
    """
    Calcula um score de confiança para uma linha digitável baseado em padrões conhecidos.
    
    A linha digitável de DARF geralmente começa com:
    - "85" (mais comum) - score 100
    - "89" (comum) - score 90
    - "88" (raro, geralmente erro de OCR) - score 50
    - Outros começando com 8 - score 70
    - Começando com 9 - score 60
    
    Args:
        digitos: String com exatamente 48 dígitos
        
    Returns:
        Score de 0 a 100 (maior = mais confiável)
    """
    if len(digitos) != 48:
        return 0
    
    # Prioriza padrões mais comuns de DARF
    if digitos.startswith("85"):
        return 100  # Padrão mais comum e confiável
    elif digitos.startswith("89"):
        return 90   # Padrão comum
    elif digitos.startswith("88"):
        return 50   # Raro, geralmente é erro de junção no OCR
    elif digitos[0] == "8":
        return 70   # Outros padrões começando com 8
    elif digitos[0] == "9":
        return 60   # Padrões começando com 9
    
    return 0


def validar_linha_digitavel(candidato: str) -> Optional[str]:
    """
    Valida e normaliza uma linha digitável candidata.
    
    A linha digitável de um DARF tem exatamente 48 dígitos.
    Se o candidato tiver mais de 48 dígitos, extrai a primeira ocorrência válida de 48 dígitos.
    
    Args:
        candidato: String contendo a linha digitável (pode ter espaços, formatação, etc.)
        
    Returns:
        String com exatamente 48 dígitos se válida, None caso contrário
    """
    if not candidato:
        return None
    
    # Remove todos os caracteres não numéricos
    digitos = re.sub(r"\D", "", str(candidato))
    
    # Verifica se tem pelo menos 48 dígitos
    if len(digitos) < 48:
        return None
    
    # Se tem exatamente 48 dígitos, retorna
    if len(digitos) == 48:
        # Valida que começa com 8 ou 9 (padrão DARF)
        if digitos[0] in ('8', '9'):
            return digitos
        return None
    
    # Se tem mais de 48 dígitos, busca a primeira ocorrência válida de 48 dígitos
    # que começa com 8 ou 9
    for i in range(len(digitos) - 47):
        candidato_48 = digitos[i:i+48]
        # Valida que começa com 8 ou 9
        if candidato_48[0] in ('8', '9'):
            return candidato_48
    
    return None


def buscar_todas_linhas_digitaveis(texto: str) -> list[tuple[str, int]]:
    """
    Busca todas as ocorrências válidas de linha digitável no texto e retorna com scores.
    
    Args:
        texto: Texto completo do PDF
        
    Returns:
        Lista de tuplas (linha_digitavel, score) ordenadas por score (maior primeiro)
    """
    resultados = []
    texto_sem_espacos = texto.replace(" ", "").replace("\n", "")
    
    # Busca todas as ocorrências de 48 dígitos consecutivos começando com 8 ou 9
    padrao_48_digitos = re.compile(r"[89]\d{47}")
    matches = padrao_48_digitos.finditer(texto_sem_espacos)
    
    for match in matches:
        linha_48 = match.group(0)
        score = calcular_score_linha_digitavel(linha_48)
        if score > 0:
            resultados.append((linha_48, score))
    
    # Remove duplicatas mantendo apenas a de maior score
    linhas_unicas = {}
    for linha, score in resultados:
        if linha not in linhas_unicas or score > linhas_unicas[linha]:
            linhas_unicas[linha] = score
    
    # Ordena por score (maior primeiro) e depois por posição no texto (primeira ocorrência)
    resultados_unicos = [(linha, score) for linha, score in linhas_unicas.items()]
    resultados_unicos.sort(key=lambda x: (-x[1], texto_sem_espacos.find(x[0])))
    
    return resultados_unicos


def extrair_linha_digitavel(lines, text=""):
    linha = None
    erro = None
    todas_ocorrencias = []

    # procurar linha inteira que satisfaça regex mais forte
    for line in lines:
        m = LINHA_DIGITAVEL_REGEX.search(line)
        if m:
            candidato_validado = validar_linha_digitavel(m.group(1))
            if candidato_validado:
                score = calcular_score_linha_digitavel(candidato_validado)
                todas_ocorrencias.append((candidato_validado, score))

    # fallback mais permissivo: linha começando com 8 ou 9 com muitos dígitos
    for line in lines:
        if re.match(r"^[89]\d{4}", line):
            digitos_na_linha = re.sub(r"\D", "", line)
            if len(digitos_na_linha) >= 40:
                candidato_validado = validar_linha_digitavel(line.strip())
                if candidato_validado:
                    score = calcular_score_linha_digitavel(candidato_validado)
                    todas_ocorrencias.append((candidato_validado, score))

    # Fallback: buscar no texto completo
    if text:
        # Busca todas as ocorrências de linha digitável no texto completo
        ocorrencias_texto = buscar_todas_linhas_digitaveis(text)
        todas_ocorrencias.extend(ocorrencias_texto)
        
        # Fallback adicional: procura padrão de linha digitável formatada
        linha_match = LINHA_DIGITAVEL_REGEX.search(text)
        if linha_match:
            candidato_validado = validar_linha_digitavel(linha_match.group(1))
            if candidato_validado:
                score = calcular_score_linha_digitavel(candidato_validado)
                todas_ocorrencias.append((candidato_validado, score))
        
        # Fallback final: tenta encontrar números que formam a linha digitável mesmo fragmentados
        numeros = re.findall(r"\d+", text)
        # Junta números grandes que podem formar a linha digitável
        linha_candidato = "".join([n for n in numeros if len(n) >= 10])
        candidato_validado = validar_linha_digitavel(linha_candidato)
        if candidato_validado:
            score = calcular_score_linha_digitavel(candidato_validado)
            todas_ocorrencias.append((candidato_validado, score))

    # Remove duplicatas mantendo apenas a de maior score
    linhas_unicas = {}
    for linha_cand, score in todas_ocorrencias:
        if linha_cand not in linhas_unicas or score > linhas_unicas[linha_cand]:
            linhas_unicas[linha_cand] = score

    # Escolhe a linha digitável com maior score
    if linhas_unicas:
        # Ordena por score (maior primeiro)
        linha_ordenada = sorted(linhas_unicas.items(), key=lambda x: -x[1])
        linha = linha_ordenada[0][0]
    else:
        linha = None

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


# ==========================
# IMPORTS DE FUNÇÕES AUXILIARES
# ==========================

# Importa funções do módulo de configuração
from app.database import get_aba_por_codigo, get_uo_por_cnpj

# Importa funções de formatação do módulo utils
try:
    from app.utils.formatters import (
        extrair_apenas_numeros,
        calcular_data_menos_um_dia,
        calcular_mes_anterior,
        limpar_valor_monetario,
        limpar_cnpj,
        limpar_mes_ano,
        limpar_data,
    )
except ImportError:
    # Fallback para compatibilidade se app.utils não estiver disponível
    # (não deve acontecer em produção, mas mantém compatibilidade)
    def extrair_apenas_numeros(texto: str) -> str:
        if not texto:
            return ""
        return re.sub(r"\D", "", str(texto))
    
    def calcular_data_menos_um_dia(data_str: str) -> str:
        if not data_str:
            return ""
        try:
            data = datetime.strptime(data_str.strip(), "%d/%m/%Y")
            data_menos_um = data - timedelta(days=1)
            return data_menos_um.strftime("%d/%m/%Y")
        except (ValueError, AttributeError):
            return ""
    
    def calcular_mes_anterior() -> str:
        hoje = datetime.now()
        if hoje.month == 1:
            mes_anterior = 12
            ano_anterior = hoje.year - 1
        else:
            mes_anterior = hoje.month - 1
            ano_anterior = hoje.year
        return f"{mes_anterior:02d}/{ano_anterior}"
    
    def limpar_valor_monetario(valor: str) -> str:
        if not valor:
            return ""
        return str(valor).replace(".", "").replace(",", "")
    
    def limpar_cnpj(cnpj: str) -> str:
        if not cnpj:
            return ""
        return str(cnpj).replace(".", "").replace("/", "").replace("-", "")
    
    def limpar_mes_ano(mes_ano: str) -> str:
        if not mes_ano:
            return ""
        return str(mes_ano).replace("/", "")
    
    def limpar_data(data: str) -> str:
        if not data:
            return ""
        return str(data).replace("/", "")


# Importa funções de formatação do módulo de serviços
try:
    from app.services.excel_generator import (
        formatar_linha_servidor,
        formatar_linha_patronal_gilrat,
    )
except ImportError:
    # Fallback para compatibilidade se app.services não estiver disponível
    # (usado quando script é executado diretamente sem Flask)
    def formatar_linha_patronal_gilrat(registro: dict) -> dict:
        arquivo = registro.get("arquivo", "") or ""
        cnpj = registro.get("cnpj", "") or ""
        numero_doc = registro.get("numero_documento", "") or ""
        linha_dig = registro.get("linha_digitavel", "") or ""
        valor_total = registro.get("valor_total_documento", "") or ""
        data_venc = registro.get("data_vencimento", "") or ""
        
        uo_contribuinte = get_uo_por_cnpj(cnpj) or ""
        nr_doc_numeros = extrair_apenas_numeros(numero_doc)
        codigo_barras_numeros = extrair_apenas_numeros(linha_dig)
        data_pagamento = calcular_data_menos_um_dia(data_venc)
        mes_comp = calcular_mes_anterior()
        historico = f"Folha INSS {mes_comp}"
        
        return {
            "Arquivo": arquivo,
            "Informe o Credor": limpar_cnpj("29.979.036/0001-40"),
            "Leitora Otica": "n",
            "Selecione com 'X'": "Patronal (GPS/DARF)",
            "Selecione a GUIA para Pagamento": "DARF",
            "Ano/Nr. Folha": "",
            "UO Contribuinte": uo_contribuinte,
            "Ordenador Despesa": "m1127166",
            "Nr Docto DARF": nr_doc_numeros,
            "Codigo de Barra": codigo_barras_numeros,
            "Valor Total do Documento": limpar_valor_monetario(valor_total),
            "Data Pagamento Prevista": limpar_data(data_pagamento),
            "Historico de Referencia": historico,
        }
    
    def formatar_linha_servidor(registro: dict) -> dict:
        arquivo = registro.get("arquivo", "") or ""
        cnpj = registro.get("cnpj", "") or ""
        numero_doc = registro.get("numero_documento", "") or ""
        linha_dig = registro.get("linha_digitavel", "") or ""
        valor_total = registro.get("valor_total_documento", "") or ""
        data_venc = registro.get("data_vencimento", "") or ""
        
        uo_contribuinte = get_uo_por_cnpj(cnpj) or ""
        nr_doc_numeros = extrair_apenas_numeros(numero_doc)
        codigo_barras_numeros = extrair_apenas_numeros(linha_dig)
        data_pagamento = calcular_data_menos_um_dia(data_venc)
        mes_comp = calcular_mes_anterior()
        historico = f"Folha INSS {mes_comp}"
        
        return {
            "Arquivo": arquivo,
            "Informe o Credor": limpar_cnpj("29.979.036/0001-40"),
            "Leitora Otica": "n",
            "Selecione com 'X'": "Consignacao (GPS/DARF)",
            "Selecione a GUIA para Pagamento": "DARF",
            "Mes/Ano de Competencia:": limpar_mes_ano(mes_comp),
            "UO Contribuinte": uo_contribuinte,
            "GMI FP": "",
            "Ordenador Despesa": "m1127166",
            "Nr Docto DARF": nr_doc_numeros,
            "Codigo de Barra": codigo_barras_numeros,
            "Valor Total do Documento": limpar_valor_monetario(valor_total),
            "Data Pagamento Prevista": limpar_data(data_pagamento),
            "Historico de Referencia": historico,
        }


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

    # salva CSV (mantém formato original para compatibilidade)
    df.to_csv(output_csv, index=False, encoding="utf-8-sig")
    
    # Separa registros por aba baseado no código para o XLSX
    registros_servidor = []
    registros_patronal = []
    
    for registro in registros:
        codigo = registro.get("codigo", "")
        aba = get_aba_por_codigo(codigo)
        
        if aba == "servidor":
            linha_formatada = formatar_linha_servidor(registro)
            registros_servidor.append(linha_formatada)
        elif aba == "patronal-gilrat":
            linha_formatada = formatar_linha_patronal_gilrat(registro)
            registros_patronal.append(linha_formatada)
        # Se aba for None, o registro não será incluído em nenhuma aba

    # Cria DataFrames para cada aba
    df_servidor = pd.DataFrame(registros_servidor) if registros_servidor else pd.DataFrame()
    df_patronal = pd.DataFrame(registros_patronal) if registros_patronal else pd.DataFrame()

    # Salva o Excel com múltiplas abas usando ExcelWriter
    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        # Escreve a aba "servidor" (mesmo que vazia)
        if registros_servidor:
            df_servidor.to_excel(writer, sheet_name="servidor", index=False)
        else:
            # Cria aba vazia com cabeçalhos
            df_vazio_servidor = pd.DataFrame(columns=formatar_linha_servidor({}).keys())
            df_vazio_servidor.to_excel(writer, sheet_name="servidor", index=False)
        
        # Escreve a aba "patronal-gilrat" (mesmo que vazia)
        if registros_patronal:
            df_patronal.to_excel(writer, sheet_name="patronal-gilrat", index=False)
        else:
            # Cria aba vazia com cabeçalhos
            df_vazio_patronal = pd.DataFrame(columns=formatar_linha_patronal_gilrat({}).keys())
            df_vazio_patronal.to_excel(writer, sheet_name="patronal-gilrat", index=False)

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