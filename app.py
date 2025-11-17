"""
Aplicação Flask para:

1. Autenticar o usuário usando conta Microsoft (Microsoft Entra ID / Azure AD)
2. Permitir upload de PDFs de DARF
3. Processar os PDFs com a função `processar_pdf` (parse_darf.py)
4. Gerar um arquivo Excel consolidado com as informações extraídas

Requer:
- Flask
- msal
- pandas
- parse_darf.py (no mesmo diretório)
"""

import os
import tempfile
from pathlib import Path
from functools import wraps

import pandas as pd
from flask import (
    Flask,
    render_template,
    request,
    send_file,
    flash,
    redirect,
    url_for,
    session,
)
from werkzeug.utils import secure_filename

import msal  # Microsoft Authentication Library
from parse_darf import processar_pdf


# ======================================================================
# CONFIGURAÇÕES BÁSICAS DO FLASK
# ======================================================================

app = Flask(__name__)

# Chave secreta usada pelo Flask para assinar cookies de sessão
# Em produção, use um valor fixo armazenado em variável de ambiente.
app.secret_key = os.urandom(24)

# Limite de tamanho do upload: 100 MB
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024

# Pasta base para arquivos temporários (usaremos subpastas dentro dela)
app.config["UPLOAD_FOLDER"] = tempfile.gettempdir()

# Extensões de arquivo permitidas para upload
ALLOWED_EXTENSIONS = {"pdf"}


# ======================================================================
# CONFIGURAÇÃO DE AUTENTICAÇÃO MICROSOFT (MSAL / ENTRA ID)
# ======================================================================

"""
Idealmente, configure estes valores via variáveis de ambiente:

export MS_CLIENT_ID="..."
export MS_CLIENT_SECRET="..."
export MS_TENANT_ID="..."

E no código, use os.getenv().
Aqui deixo as duas opções (env + placeholder).
"""

CLIENT_ID = os.getenv("MS_CLIENT_ID", "7457428f-727b-4205-aa2a-a28da53b2b45")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "ecf8Q~YrXO7YfT6B1e9Nqkps-n-Gm2PqfJl9tdbh")

# Se quiser usar um tenant específico, substitua "common" pelo MS_TENANT_ID
TENANT_ID = os.getenv("MS_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# Caminho de redirecionamento (precisa bater com o configurado no portal)
REDIRECT_PATH = "/auth/redirect"

# Escopos de permissão que o app solicita (User.Read já é suficiente para pegar dados básicos)
SCOPE = ["User.Read"]

# Chave que usaremos para armazenar o usuário na sessão Flask
SESSION_USER_KEY = "user"


# ======================================================================
# FUNÇÕES AUXILIARES: ARQUIVOS & AUTENTICAÇÃO
# ======================================================================

def allowed_file(filename: str) -> bool:
    """
    Verifica se o nome de arquivo possui uma extensão permitida.

    Regras:
    - Deve conter um ponto (.)
    - Tudo após o último ponto deve estar em ALLOWED_EXTENSIONS
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _build_msal_app(cache=None) -> msal.ConfidentialClientApplication:
    """
    Cria uma instância da aplicação confidencial MSAL.

    Essa aplicação é responsável por:
    - Montar a URL de login (authorization request)
    - Trocar o "authorization code" por tokens (access_token, id_token etc.)
    """
    return msal.ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache,
    )


def _build_auth_url(scopes=None) -> str:
    """
    Gera a URL de login da Microsoft para o fluxo Authorization Code.

    Parâmetros:
    - scopes: lista de permissões (scopes) que desejamos solicitar.

    Retorno:
    - URL completa para onde devemos redirecionar o usuário.
    """
    # redirect_uri precisa ser exatamente o mesmo registrado no portal
    redirect_uri = request.host_url.strip("/") + REDIRECT_PATH
    return _build_msal_app().get_authorization_request_url(
        scopes or [],
        redirect_uri=redirect_uri,
    )


def login_required(view_func):
    """
    Decorator que protege rotas que exigem usuário autenticado.

    Uso:
    @app.route("/alguma_rota")
    @login_required
    def minha_rota():
        ...

    Lógica:
    - Se SESSION_USER_KEY não estiver na sessão, redireciona para /login
    - Caso contrário, executa a função da rota normalmente
    """

    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if SESSION_USER_KEY not in session:
            # Usuário não autenticado -> envia para tela de login Microsoft
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapper


# ======================================================================
# ROTAS DE AUTENTICAÇÃO (LOGIN / CALLBACK / LOGOUT)
# ======================================================================

@app.route("/login")
def login():
    """
    Inicia o fluxo de autenticação com a Microsoft.

    A lógica é:
    1. Gera a URL de autorização (authorization request) com os escopos desejados.
    2. Redireciona o usuário para essa URL.
    3. A Microsoft fará o login e, ao final, chamará nossa rota de callback
       em REDIRECT_PATH (/auth/redirect).
    """
    auth_url = _build_auth_url(SCOPE)
    return redirect(auth_url)


@app.route(REDIRECT_PATH)
def authorized():
    """
    Rota de callback chamada pela Microsoft após o login.

    Responsabilidades:
    - Receber o "code" vindo como query string (?code=...)
    - Trocar esse code por tokens através da MSAL
    - Extrair as informações básicas do usuário (nome, e-mail)
    - Armazenar os dados do usuário na sessão Flask
    """

    # Se não veio "code" na URL, algo deu errado
    if "code" not in request.args:
        flash("Nenhum código de autenticação recebido.", "error")
        return redirect(url_for("index"))

    code = request.args["code"]

    # Mesmo redirect_uri usado na geração da URL de login
    redirect_uri = request.host_url.strip("/") + REDIRECT_PATH

    # Troca o authorization code por tokens
    result = _build_msal_app().acquire_token_by_authorization_code(
        code,
        scopes=SCOPE,
        redirect_uri=redirect_uri,
    )

    # Se veio erro, mostra mensagem amigável e volta para home
    if "error" in result:
        error_desc = result.get("error_description") or result.get("error")
        flash(f"Erro na autenticação: {error_desc}", "error")
        return redirect(url_for("index"))

    # id_token_claims contém informações básicas sobre o usuário autenticado
    claims = result.get("id_token_claims", {}) or {}

    user = {
        "name": claims.get("name"),
        # preferred_username costuma ser o e-mail principal
        "email": claims.get("preferred_username")
        or (claims.get("emails", [None])[0] if claims.get("emails") else None),
    }

    # Armazena o usuário na sessão
    session[SESSION_USER_KEY] = user
    flash(f"Autenticado como {user.get('email')}", "success")

    # Depois de logado, envia o usuário para a página inicial
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    """
    Remove os dados do usuário da sessão (logout local do app).

    Obs.: isso não faz logout global da conta Microsoft no navegador,
    apenas "desloga" o usuário deste aplicativo Flask.
    """
    session.pop(SESSION_USER_KEY, None)
    flash("Você saiu do sistema.", "success")
    return redirect(url_for("index"))


# ======================================================================
# ROTAS PRINCIPAIS DO APP (PROTEGIDAS POR LOGIN)
# ======================================================================

@app.route("/")
@login_required
def index():
    """
    Página inicial com o formulário de upload de PDFs.

    - Exibe o template `index.html`
    - Passa o objeto `user` para o template (dados do usuário logado)
    """
    user = session.get(SESSION_USER_KEY)
    return render_template("index.html", user=user)


@app.route("/upload", methods=["POST"])
@login_required
def upload_files():
    """
    Trata o upload de múltiplos arquivos PDF e gera um XLSX consolidado.

    Fluxo:
    1. Lê os arquivos enviados via formulário (campo "files").
    2. Filtra apenas arquivos com extensão .pdf.
    3. Salva cada PDF em uma pasta temporária.
    4. Para cada PDF, chama `processar_pdf` (de parse_darf.py).
       - Se houver erro específico no PDF, registra um dicionário com erros.
    5. Gera um pandas.DataFrame com todos os resultados.
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
                resultado = processar_pdf(file_path)
                registros.append(resultado)
            except Exception as e:
                # Caso o PDF dê erro, registramos uma linha com os campos em None
                # e mensagens de erro para cada campo.
                msg = f"Erro ao processar PDF: {str(e)}"
                registros.append(
                    {
                        "arquivo": filename,
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
