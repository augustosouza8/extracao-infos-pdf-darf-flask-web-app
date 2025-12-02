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
import tempfile
from pathlib import Path

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

        # Cria DataFrame com todos os registros (sucesso + erros)
        df = pd.DataFrame(registros)

        # Gera o caminho final do arquivo XLSX
        output_path = temp_dir / "resultado_darfs.xlsx"

        # Salva o DataFrame em formato Excel
        df.to_excel(output_path, index=False)

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
