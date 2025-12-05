"""
Rotas principais da aplicação.

Contém as rotas para a página inicial e upload de arquivos.
"""

import tempfile
from pathlib import Path
from flask import Blueprint, render_template, request, send_file, flash, redirect, url_for
from werkzeug.utils import secure_filename

from app.services.pdf_parser import processar_pdf
from app.utils.validators import allowed_file
from app.utils.errors import coletar_erros_registro
from app.services.excel_generator import (
    formatar_linha_servidor,
    formatar_linha_patronal_gilrat,
    gerar_excel,
)
from app.database import get_aba_por_codigo

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    """
    Página inicial com o formulário de upload de PDFs.

    - Exibe o template `index.html`
    """
    return render_template("index.html")


@bp.route("/upload", methods=["POST"])
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
        return redirect(url_for("main.index"))

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
        return redirect(url_for("main.index"))

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
            return redirect(url_for("main.index"))

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
            aba = get_aba_por_codigo(codigo)
            
            if aba == "servidor":
                linha_formatada = formatar_linha_servidor(registro)
                registros_servidor.append(linha_formatada)
            elif aba == "patronal-gilrat":
                linha_formatada = formatar_linha_patronal_gilrat(registro)
                registros_patronal.append(linha_formatada)
            # Se aba for None, o registro não será incluído em nenhuma aba

        # Gera o caminho final do arquivo XLSX
        output_path = temp_dir / "resultado_darfs.xlsx"

        # Gera o Excel
        gerar_excel(registros_servidor, registros_patronal, todos_erros, output_path)

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
        return redirect(url_for("main.index"))

