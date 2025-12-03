"""
Aplicação Flask para:

1. Permitir upload de PDFs de DARF
2. Processar os PDFs com a função `processar_pdf` (parse_darf.py)
3. Gerar um arquivo Excel consolidado com as informações extraídas

Requer:
- Flask
- pandas
- parse_darf.py (no mesmo diretório)
"""

import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    send_file,
    flash,
    redirect,
    url_for,
)
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
from parse_darf import processar_pdf

load_dotenv()


# ======================================================================
# CONFIGURAÇÕES BÁSICAS DO FLASK
# ======================================================================

app = Flask(__name__)

# Chave secreta usada pelo Flask para assinar cookies de sessão
# Usa FLASK_SECRET_KEY do ambiente ou gera uma chave aleatória (não persistente)
app.secret_key = os.getenv("FLASK_SECRET_KEY", os.urandom(24))

# Limite de tamanho do upload: 100 MB
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

# Pasta base para arquivos temporários (usaremos subpastas dentro dela)
app.config["UPLOAD_FOLDER"] = tempfile.gettempdir()

# Extensões de arquivo permitidas para upload
ALLOWED_EXTENSIONS = {"pdf"}


# ======================================================================
# FUNÇÕES AUXILIARES: ARQUIVOS
# ======================================================================

def allowed_file(filename: str) -> bool:
    """
    Verifica se o nome de arquivo possui uma extensão permitida.

    Regras:
    - Deve conter um ponto (.)
    - Tudo após o último ponto deve estar em ALLOWED_EXTENSIONS
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


# ======================================================================
# FUNÇÕES AUXILIARES: PROCESSAMENTO DE DARF
# ======================================================================

# Mapeamento CNPJ -> UO Contribuinte
MAPEAMENTO_CNPJ_UO = {
    "18.715.565/0001-10": "1071",
    "16.745.465/0001-01": "1081",
    "07.256.298/0001-44": "1101",
    "16.907.746/0001-13": "1191",
    "19.377.514/0001-99": "1221",
    "18.715.573/0001-67": "1231",
    "19.138.890/0001-20": "1271",
    "18.715.581/0001-03": "1301",
    "00.957.404/0001-78": "1371",
    "05.487.631/0001-09": "1451",
    "05.465.167/0001-41": "1481",
    "05.475.103/0001-21": "1491",
    "05.461.142/0001-70": "1501",
    "18.715.532/0001-70": "1511",
    "05.585.681/0001-10": "1521",
    "08.715.327/0001-51": "1541",
    "13.235.618/0001-82": "1631",
    "50.629.390/0001-31": "1711",
    "50.941.185/0001-07": "1721",
}


def determinar_aba(codigo: str) -> Optional[str]:
    """
    Determina em qual aba o registro deve ser inserido baseado no código.
    
    Args:
        codigo: Código extraído da DARF
        
    Returns:
        "servidor" se código for 1082 ou 1099,
        "patronal-gilrat" se código for 1138 ou 1646,
        None caso contrário
    """
    if not codigo:
        return None
    
    codigo_str = str(codigo).strip()
    if codigo_str in ("1082", "1099"):
        return "servidor"
    elif codigo_str in ("1138", "1646"):
        return "patronal-gilrat"
    return None


def mapear_cnpj_uo(cnpj: str) -> str:
    """
    Mapeia um CNPJ para seu código UO Contribuinte correspondente.
    
    Args:
        cnpj: CNPJ formatado ou não
        
    Returns:
        Código UO se encontrado, string vazia caso contrário
    """
    if not cnpj:
        return ""
    
    # Normaliza o CNPJ para o formato esperado (com pontos e barras)
    cnpj_formatado = cnpj.strip()
    
    # Se o CNPJ não estiver formatado, tenta formatar
    if re.match(r"^\d{14}$", cnpj_formatado):
        # Formata: XX.XXX.XXX/XXXX-XX
        cnpj_formatado = f"{cnpj_formatado[:2]}.{cnpj_formatado[2:5]}.{cnpj_formatado[5:8]}/{cnpj_formatado[8:12]}-{cnpj_formatado[12:14]}"
    
    return MAPEAMENTO_CNPJ_UO.get(cnpj_formatado, "")


def extrair_apenas_numeros(texto: str) -> str:
    """
    Extrai apenas os dígitos numéricos de uma string.
    
    Args:
        texto: String que pode conter números e outros caracteres
        
    Returns:
        String contendo apenas dígitos
    """
    if not texto:
        return ""
    return re.sub(r"\D", "", str(texto))


def calcular_data_menos_um_dia(data_str: str) -> str:
    """
    Subtrai 1 dia de uma data no formato DD/MM/AAAA.
    
    Args:
        data_str: Data no formato DD/MM/AAAA
        
    Returns:
        Data com 1 dia a menos no formato DD/MM/AAAA, ou string vazia se inválida
    """
    if not data_str:
        return ""
    
    try:
        # Tenta parsear a data
        data = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        data_menos_um = data - timedelta(days=1)
        return data_menos_um.strftime("%d/%m/%Y")
    except (ValueError, AttributeError):
        return ""


def calcular_mes_anterior() -> str:
    """
    Calcula o mês anterior à data atual no formato MM/AAAA.
    
    Returns:
        String no formato MM/AAAA do mês anterior
    """
    hoje = datetime.now()
    # Se for janeiro, o mês anterior é dezembro do ano anterior
    if hoje.month == 1:
        mes_anterior = 12
        ano_anterior = hoje.year - 1
    else:
        mes_anterior = hoje.month - 1
        ano_anterior = hoje.year
    
    return f"{mes_anterior:02d}/{ano_anterior}"


def limpar_valor_monetario(valor: str) -> str:
    """
    Remove pontos e vírgulas de um valor monetário.
    Ex: "1.386,00" -> "138600"
    
    Args:
        valor: String com valor monetário formatado
        
    Returns:
        String apenas com dígitos
    """
    if not valor:
        return ""
    return str(valor).replace(".", "").replace(",", "")


def limpar_cnpj(cnpj: str) -> str:
    """
    Remove pontos, barras e hífens de um CNPJ.
    Ex: "29.979.036/0001-40" -> "29979036000140"
    
    Args:
        cnpj: String com CNPJ formatado
        
    Returns:
        String apenas com dígitos
    """
    if not cnpj:
        return ""
    return str(cnpj).replace(".", "").replace("/", "").replace("-", "")


def limpar_mes_ano(mes_ano: str) -> str:
    """
    Remove a barra de um valor mês/ano.
    Ex: "11/2025" -> "112025"
    
    Args:
        mes_ano: String no formato MM/AAAA
        
    Returns:
        String apenas com dígitos
    """
    if not mes_ano:
        return ""
    return str(mes_ano).replace("/", "")


def limpar_data(data: str) -> str:
    """
    Remove as barras de uma data.
    Ex: "19/10/2025" -> "19102025"
    
    Args:
        data: String no formato DD/MM/AAAA
        
    Returns:
        String apenas com dígitos
    """
    if not data:
        return ""
    return str(data).replace("/", "")


# ======================================================================
# FUNÇÕES DE FORMATAÇÃO DE LINHAS
# ======================================================================

def formatar_linha_patronal_gilrat(registro: dict) -> dict:
    """
    Formata um registro para a aba "patronal-gilrat".
    
    Args:
        registro: Dicionário com campos extraídos do PDF
        
    Returns:
        Dicionário com colunas formatadas para a aba patronal-gilrat
    """
    arquivo = registro.get("arquivo", "") or ""
    cnpj = registro.get("cnpj", "") or ""
    numero_doc = registro.get("numero_documento", "") or ""
    linha_dig = registro.get("linha_digitavel", "") or ""
    valor_total = registro.get("valor_total_documento", "") or ""
    data_venc = registro.get("data_vencimento", "") or ""
    
    uo_contribuinte = mapear_cnpj_uo(cnpj)
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
    """
    Formata um registro para a aba "servidor".
    
    Args:
        registro: Dicionário com campos extraídos do PDF
        
    Returns:
        Dicionário com colunas formatadas para a aba servidor
    """
    arquivo = registro.get("arquivo", "") or ""
    cnpj = registro.get("cnpj", "") or ""
    numero_doc = registro.get("numero_documento", "") or ""
    linha_dig = registro.get("linha_digitavel", "") or ""
    valor_total = registro.get("valor_total_documento", "") or ""
    data_venc = registro.get("data_vencimento", "") or ""
    
    uo_contribuinte = mapear_cnpj_uo(cnpj)
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


# ======================================================================
# ROTAS PRINCIPAIS DO APP
# ======================================================================

@app.route("/")
def index():
    """
    Página inicial com o formulário de upload de PDFs.

    - Exibe o template `index.html`
    """
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload_files():
    """
    Trata o upload de múltiplos arquivos PDF e gera um XLSX consolidado.

    Fluxo:
    1. Lê os arquivos enviados via formulário (campo "files").
    2. Filtra apenas arquivos com extensão .pdf.
    3. Salva cada PDF em uma pasta temporária.
    4. Para cada PDF, chama `processar_pdf` (de parse_darf.py).
       - Processa todas as páginas do PDF.
       - Cada página gera uma linha separada no Excel.
       - O nome do arquivo na coluna "arquivo" inclui o número da página
         (ex: "arquivo.pdf - Página 1", "arquivo.pdf - Página 2").
       - Se houver erro específico no PDF, registra um dicionário com erros.
    5. Gera um pandas.DataFrame com todos os resultados (todas as páginas).
    6. Salva um arquivo `resultado_darfs.xlsx` em disco (pasta temporária).
    7. Retorna o arquivo para download via `send_file`.
    """

    # Verifica se o formulário realmente trouxe o campo "files"
    if "files" not in request.files:
        flash("Nenhum arquivo selecionado.", "error")
        return redirect(url_for("index"))

    files = request.files.getlist("files")

    # Filtra apenas arquivos que tenham nome e extensão permitida
    pdf_files = []
    for file in files:
        if file and file.filename and allowed_file(file.filename):
            pdf_files.append(file)

    if not pdf_files:
        flash(
            "Nenhum arquivo PDF válido encontrado. "
            "Por favor, selecione arquivos com extensão .pdf.",
            "error",
        )
        return redirect(url_for("index"))

    # Cria uma pasta temporária exclusiva para esta requisição
    temp_dir = Path(tempfile.mkdtemp())
    registros = []

    try:
        # Percorre cada arquivo enviado
        for file in pdf_files:
            # Trata o nome do arquivo para evitar problemas de segurança
            filename = secure_filename(file.filename)
            file_path = temp_dir / filename

            # Salva o conteúdo do upload em disco
            file.save(str(file_path))

            # Tenta processar o PDF com a lógica de parse_darf.py
            try:
                # processar_pdf agora retorna uma lista de resultados (um por página)
                resultados_paginas = processar_pdf(file_path)
                registros.extend(resultados_paginas)
            except Exception as e:
                # Caso o PDF dê erro, registramos uma linha com os campos em None
                # e mensagens de erro para cada campo (pelo menos uma página)
                msg = f"Erro ao processar PDF: {str(e)}"
                registros.append(
                    {
                        "arquivo": f"{filename} - Página 1",
                        "cnpj": None,
                        "cnpj_erro": msg,
                        "razao_social": None,
                        "razao_social_erro": msg,
                        "periodo_apuracao": None,
                        "periodo_apuracao_erro": msg,
                        "data_vencimento": None,
                        "data_vencimento_erro": msg,
                        "numero_documento": None,
                        "numero_documento_erro": msg,
                        "valor_total_documento": None,
                        "valor_total_documento_erro": msg,
                        "codigo": None,
                        "codigo_erro": msg,
                        "denominacao": None,
                        "denominacao_erro": msg,
                        "linha_digitavel": None,
                        "linha_digitavel_erro": msg,
                    }
                )

        # Se por alguma razão não houver nenhum registro, avisamos o usuário
        if not registros:
            flash("Nenhum arquivo foi processado com sucesso.", "error")
            return redirect(url_for("index"))

        # Separa registros por aba baseado no código
        registros_servidor = []
        registros_patronal = []
        
        for registro in registros:
            codigo = registro.get("codigo", "")
            aba = determinar_aba(codigo)
            
            if aba == "servidor":
                linha_formatada = formatar_linha_servidor(registro)
                registros_servidor.append(linha_formatada)
            elif aba == "patronal-gilrat":
                linha_formatada = formatar_linha_patronal_gilrat(registro)
                registros_patronal.append(linha_formatada)
            # Se aba for None, o registro não será incluído em nenhuma aba

        # Gera o caminho final do arquivo XLSX
        output_path = temp_dir / "resultado_darfs.xlsx"

        # Cria DataFrames para cada aba
        df_servidor = pd.DataFrame(registros_servidor) if registros_servidor else pd.DataFrame()
        df_patronal = pd.DataFrame(registros_patronal) if registros_patronal else pd.DataFrame()

        # Salva o Excel com múltiplas abas usando ExcelWriter
        with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
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

        # Envia o arquivo para download
        return send_file(
            str(output_path),
            mimetype=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
            as_attachment=True,
            download_name="resultado_darfs.xlsx",
        )

    except Exception as e:
        # Captura qualquer erro inesperado no fluxo geral
        flash(f"Ocorreu um erro inesperado: {str(e)}", "error")
        return redirect(url_for("index"))


# ======================================================================
# PONTO DE ENTRADA
# ======================================================================

if __name__ == "__main__":
    """
    Executa o servidor Flask em modo de desenvolvimento.

    - host="0.0.0.0" permite acesso a partir de outras máquinas na rede
      (se necessário); altere para "127.0.0.1" se quiser restringir.
    - debug=True recarrega o servidor automaticamente em mudanças de código.
      Em produção, o ideal é usar um servidor WSGI (gunicorn, etc.).
    """
    app.run(debug=True, host="0.0.0.0", port=5000)
