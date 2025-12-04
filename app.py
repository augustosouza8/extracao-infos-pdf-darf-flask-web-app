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
    jsonify,
)
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
from parse_darf import processar_pdf
from config_db import (
    get_aba_por_codigo,
    get_uo_por_cnpj,
    get_todos_codigos,
    get_todos_cnpjs,
    adicionar_codigo,
    remover_codigo,
    adicionar_cnpj,
    remover_cnpj,
)

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

def determinar_aba(codigo: str) -> Optional[str]:
    """
    Determina em qual aba o registro deve ser inserido baseado no código.
    
    Args:
        codigo: Código extraído da DARF
        
    Returns:
        "servidor", "patronal-gilrat" ou None se não encontrado
    """
    return get_aba_por_codigo(codigo)


def mapear_cnpj_uo(cnpj: str) -> str:
    """
    Mapeia um CNPJ para seu código UO Contribuinte correspondente.
    
    Args:
        cnpj: CNPJ formatado ou não
        
    Returns:
        Código UO se encontrado, string vazia caso contrário
    """
    uo = get_uo_por_cnpj(cnpj)
    return uo if uo else ""


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
# FUNÇÕES DE COLETA E FORMATAÇÃO DE ERROS
# ======================================================================

def coletar_erros_registro(registro: dict) -> list[dict]:
    """
    Coleta todos os erros de um registro processado.
    
    Args:
        registro: Dicionário com campos extraídos e mensagens de erro
        
    Returns:
        Lista de dicionários com informações de erro estruturadas
    """
    erros = []
    arquivo = registro.get("arquivo", "Desconhecido")
    
    # Mapeamento de campos e seus erros correspondentes
    campos_erro = [
        ("cnpj", "cnpj_erro", "CNPJ"),
        ("razao_social", "razao_social_erro", "Razão Social"),
        ("periodo_apuracao", "periodo_apuracao_erro", "Período de Apuração"),
        ("data_vencimento", "data_vencimento_erro", "Data de Vencimento"),
        ("numero_documento", "numero_documento_erro", "Número do Documento"),
        ("valor_total_documento", "valor_total_documento_erro", "Valor Total do Documento"),
        ("codigo", "codigo_erro", "Código"),
        ("denominacao", "denominacao_erro", "Denominação"),
        ("linha_digitavel", "linha_digitavel_erro", "Linha Digitável"),
    ]
    
    # Coleta erros de campos individuais
    for campo, campo_erro, nome_campo in campos_erro:
        valor = registro.get(campo)
        erro = registro.get(campo_erro)
        
        if erro:
            # Determina tipo de erro baseado na mensagem
            erro_lower = erro.lower()
            tipo_erro = "Extração"
            severidade = "Crítico"
            
            if "inválido" in erro_lower or "formato" in erro_lower or "dígitos verificadores" in erro_lower:
                tipo_erro = "Validação"
                severidade = "Crítico"
            elif "não encontrado" in erro_lower or "não encontrada" in erro_lower:
                tipo_erro = "Extração"
                severidade = "Crítico"
            elif "pdf vazio" in erro_lower or "erro geral" in erro_lower or "erro ao processar" in erro_lower:
                tipo_erro = "Processamento"
                severidade = "Crítico"
            elif "ocr" in erro_lower or "texto insuficiente" in erro_lower:
                tipo_erro = "Processamento"
                severidade = "Aviso"
            
            erros.append({
                "arquivo": arquivo,
                "campo": nome_campo,
                "tipo_erro": tipo_erro,
                "mensagem": erro,
                "valor_extraido": str(valor) if valor is not None else "",
                "severidade": severidade,
            })
    
    # Verifica erros de mapeamento
    codigo = registro.get("codigo")
    if codigo and not registro.get("codigo_erro"):
        # Código foi extraído com sucesso, mas verifica se está mapeado
        aba = determinar_aba(codigo)
        if not aba:
            erros.append({
                "arquivo": arquivo,
                "campo": "Código",
                "tipo_erro": "Mapeamento",
                "mensagem": f"Código '{codigo}' extraído mas não mapeado para nenhuma aba (servidor ou patronal-gilrat)",
                "valor_extraido": codigo,
                "severidade": "Aviso",
            })
    
    cnpj = registro.get("cnpj")
    if cnpj and not registro.get("cnpj_erro"):
        # CNPJ foi extraído com sucesso, mas verifica se tem UO mapeada
        uo = mapear_cnpj_uo(cnpj)
        if not uo:
            erros.append({
                "arquivo": arquivo,
                "campo": "CNPJ",
                "tipo_erro": "Mapeamento",
                "mensagem": f"CNPJ '{cnpj}' extraído mas não possui UO Contribuinte mapeada",
                "valor_extraido": cnpj,
                "severidade": "Aviso",
            })
    
    return erros


def formatar_linha_erro(erro: dict) -> dict:
    """
    Formata um erro para a aba de erros do Excel.
    
    Args:
        erro: Dicionário com informações de erro
        
    Returns:
        Dicionário formatado para a aba de erros
    """
    return {
        "Arquivo": erro.get("arquivo", ""),
        "Campo": erro.get("campo", ""),
        "Tipo de Erro": erro.get("tipo_erro", ""),
        "Mensagem": erro.get("mensagem", ""),
        "Valor Extraído": erro.get("valor_extraido", ""),
        "Severidade": erro.get("severidade", ""),
    }


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

        # Separa registros por aba baseado no código e coleta erros
        registros_servidor = []
        registros_patronal = []
        todos_erros = []
        
        for registro in registros:
            # Coleta erros do registro
            erros_registro = coletar_erros_registro(registro)
            todos_erros.extend(erros_registro)
            
            # Separa por aba
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
        
        # Formata erros para a aba de erros
        erros_formatados = [formatar_linha_erro(erro) for erro in todos_erros]
        df_erros = pd.DataFrame(erros_formatados) if erros_formatados else pd.DataFrame()

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
            
            # Escreve a aba "erros" (mesmo que vazia)
            if erros_formatados:
                df_erros.to_excel(writer, sheet_name="erros", index=False)
            else:
                # Cria aba vazia com cabeçalhos
                df_vazio_erros = pd.DataFrame(columns=["Arquivo", "Campo", "Tipo de Erro", "Mensagem", "Valor Extraído", "Severidade"])
                df_vazio_erros.to_excel(writer, sheet_name="erros", index=False)

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
# ROTAS API PARA GERENCIAMENTO DE REGRAS
# ======================================================================

@app.route("/api/regras", methods=["GET"])
def api_get_regras():
    """
    Retorna todas as regras (códigos e CNPJs).
    
    Returns:
        JSON com códigos e CNPJs
    """
    try:
        codigos = get_todos_codigos()
        cnpjs = get_todos_cnpjs()
        return jsonify({
            "codigos": codigos,
            "cnpjs": cnpjs,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/regras/codigo", methods=["POST"])
def api_adicionar_codigo():
    """
    Adiciona um novo código → aba.
    
    Body JSON:
        {
            "codigo": "1234",
            "aba": "servidor" ou "patronal-gilrat"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        codigo = data.get("codigo", "").strip()
        aba = data.get("aba", "").strip()
        
        if not codigo or not aba:
            return jsonify({"error": "Código e aba são obrigatórios"}), 400
        
        sucesso, mensagem = adicionar_codigo(codigo, aba)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/regras/codigo/<codigo>", methods=["DELETE"])
def api_remover_codigo(codigo):
    """
    Remove um código → aba.
    
    Args:
        codigo: Código a remover
    """
    try:
        sucesso, mensagem = remover_codigo(codigo)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/regras/cnpj", methods=["POST"])
def api_adicionar_cnpj():
    """
    Adiciona um novo CNPJ → UO Contribuinte.
    
    Body JSON:
        {
            "cnpj": "12.345.678/0001-90",
            "uo_contribuinte": "1071"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        cnpj = data.get("cnpj", "").strip()
        uo_contribuinte = data.get("uo_contribuinte", "").strip()
        
        if not cnpj or not uo_contribuinte:
            return jsonify({"error": "CNPJ e UO Contribuinte são obrigatórios"}), 400
        
        sucesso, mensagem = adicionar_cnpj(cnpj, uo_contribuinte)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/regras/cnpj/<path:cnpj>", methods=["DELETE"])
def api_remover_cnpj(cnpj):
    """
    Remove um CNPJ → UO Contribuinte.
    
    Args:
        cnpj: CNPJ a remover (formatado ou não)
    """
    try:
        sucesso, mensagem = remover_cnpj(cnpj)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
