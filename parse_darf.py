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

def carregar_linhas_pdf(pdf_path: Path):
    """Extrai o texto da primeira página do PDF e devolve como lista de linhas normalizadas."""
    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            return []
        page = pdf.pages[0]
        text = page.extract_text() or ""
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

def extrair_cnpj_e_razao_social(lines):
    value = None
    erro = None
    razao = None
    erro_razao = None

    for line in lines:
        m = CNPJ_REGEX.search(line)
        if m:
            value = m.group(0)
            # tudo após o cnpj na mesma linha = razão social
            razao = line[m.end():].strip()
            break

    if value is None:
        erro = "CNPJ não encontrado no texto."
    elif not validar_cnpj(value):
        erro = "CNPJ encontrado, porém inválido pelos dígitos verificadores."

    if razao is None:
        erro_razao = "Razão social não encontrada na linha do CNPJ."

    return value, erro, razao, erro_razao


def extrair_periodo_vencimento_numdoc(lines):
    periodo = None
    periodo_erro = None
    vencimento = None
    vencimento_erro = None
    num_doc = None
    num_doc_erro = None

    # Estratégia principal: achar linha de rótulo e pegar próxima
    idx, _ = encontrar_primeira_linha_com(lines, "Período de Apuração")
    if idx is not None and idx + 1 < len(lines):
        valores_line = lines[idx + 1]
        # Ex: '30/09/2025 20/10/2025 07.01.25275.0746065-9'
        m = re.search(
            r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})\s+([\d\.\-]+)",
            valores_line
        )
        if m:
            periodo = m.group(1)
            vencimento = m.group(2)
            num_doc = m.group(3)

    # Fallback para número do documento pela linha "Número:"
    if num_doc is None:
        for line in lines:
            m = re.search(r"Número:\s*([\d\.\-]+)", line)
            if m:
                num_doc = m.group(1)
                break

    # Validar datas
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


def extrair_valor_total(lines):
    valor = None
    erro = None

    idx, _ = encontrar_primeira_linha_com(lines, "Valor Total do Documento")
    candidate_lines = []

    if idx is not None:
        # pegar algumas linhas depois do rótulo
        for offset in range(1, 4):
            if idx + offset < len(lines):
                candidate_lines.append(lines[idx + offset])

    # procurar primeiro valor monetário nessas linhas
    for line in candidate_lines:
        m = VALOR_REGEX.search(line)
        if m:
            valor = m.group(0)
            break

    # Fallback: procurar "Valor:" na parte inferior
    if valor is None:
        for line in lines:
            if "Valor:" in line:
                m = VALOR_REGEX.search(line)
                if m:
                    valor = m.group(0)
                    break

    if valor is None:
        erro = "Valor total do documento não encontrado."
    elif not validar_valor_br(valor):
        erro = "Valor total do documento com formato inválido."

    return valor, erro


def extrair_codigo_e_denom(lines):
    codigo = None
    codigo_erro = None
    denom = None
    denom_erro = None

    idx, _ = encontrar_primeira_linha_com(lines, "Composição do Documento de Arrecadação")
    if idx is not None:
        for j in range(idx + 1, len(lines)):
            line = lines[j]
            m = re.match(r"\s*(\d{4})\s+(.+)", line)
            if m:
                codigo = m.group(1)
                resto = m.group(2)
                # achar primeiro valor monetário no resto
                vm = VALOR_REGEX.search(resto)
                if vm:
                    denom = resto[:vm.start()].strip()
                else:
                    denom = resto.strip()
                break

    if codigo is None:
        codigo_erro = "Código não encontrado na composição do documento."
    if not denom:
        denom_erro = "Denominação não encontrada ou vazia."

    return codigo, codigo_erro, denom, denom_erro


def extrair_linha_digitavel(lines):
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

    if linha is None:
        erro = "Linha digitável não encontrada."
    return linha, erro


# ==========================
# PIPELINE PRINCIPAL
# ==========================

def processar_pdf(pdf_path: Path) -> dict:
    """
    Processa um DARF em PDF e retorna um dicionário com
    campos + mensagens de erro por campo.
    """
    resultado = {
        "arquivo": pdf_path.name,
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

    lines = carregar_linhas_pdf(pdf_path)

    # CNPJ + Razão Social
    cnpj, cnpj_erro, razao, razao_erro = extrair_cnpj_e_razao_social(lines)
    resultado["cnpj"] = cnpj
    resultado["cnpj_erro"] = cnpj_erro
    resultado["razao_social"] = razao
    resultado["razao_social_erro"] = razao_erro

    # Período, Vencimento, Número do Documento
    (periodo, periodo_erro,
     venc, venc_erro,
     num_doc, num_doc_erro) = extrair_periodo_vencimento_numdoc(lines)
    resultado["periodo_apuracao"] = periodo
    resultado["periodo_apuracao_erro"] = periodo_erro
    resultado["data_vencimento"] = venc
    resultado["data_vencimento_erro"] = venc_erro
    resultado["numero_documento"] = num_doc
    resultado["numero_documento_erro"] = num_doc_erro

    # Valor Total
    valor_total, valor_erro = extrair_valor_total(lines)
    resultado["valor_total_documento"] = valor_total
    resultado["valor_total_documento_erro"] = valor_erro

    # Código + Denominação
    codigo, codigo_erro, denom, denom_erro = extrair_codigo_e_denom(lines)
    resultado["codigo"] = codigo
    resultado["codigo_erro"] = codigo_erro
    resultado["denominacao"] = denom
    resultado["denominacao_erro"] = denom_erro

    # Linha digitável
    linha, linha_erro = extrair_linha_digitavel(lines)
    resultado["linha_digitavel"] = linha
    resultado["linha_digitavel_erro"] = linha_erro

    return resultado


def processar_pasta(pasta_pdf: Path, output_csv: Path, output_xlsx: Path):
    pdf_files = sorted(pasta_pdf.glob("*.pdf"))
    if not pdf_files:
        print(f"Nenhum PDF encontrado em: {pasta_pdf}")
        return

    registros = []
    for pdf in pdf_files:
        print(f"Processando: {pdf.name}")
        try:
            registros.append(processar_pdf(pdf))
        except Exception as e:
            # em caso de erro geral, registra linha com erro genérico
            registros.append({
                "arquivo": pdf.name,
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