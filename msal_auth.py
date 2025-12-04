"""
Módulo de autenticação Microsoft (MSAL / Entra ID) para Flask.

Este módulo pode ser importado em aplicativos Flask para adicionar
autenticação via contas Microsoft.

Uso básico:
    from msal_auth import setup_msal_auth, login_required
    
    app = Flask(__name__)
    setup_msal_auth(app)
    
    @app.route("/")
    @login_required
    def index():
        ...
"""

import os
from functools import wraps
from flask import redirect, url_for, session, request, flash

import msal  # Microsoft Authentication Library
from dotenv import load_dotenv

load_dotenv()

# ======================================================================
# CONFIGURAÇÃO DE AUTENTICAÇÃO MICROSOFT (MSAL / ENTRA ID)
# ======================================================================

"""
Idealmente, configure estes valores via variáveis de ambiente:

export MS_CLIENT_ID="..."
export MS_CLIENT_SECRET="..."
export MS_TENANT_ID="..."

E no código, use os.getenv().
"""

CLIENT_ID = os.getenv("MS_CLIENT_ID", "INSERIR_CLIENT_ID_AQUI")
CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET", "INSERIR_CLIENT_SECRET_AQUI")

# Se quiser usar um tenant específico, substitua "common" pelo MS_TENANT_ID
TENANT_ID = os.getenv("MS_TENANT_ID", "common")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"

# Caminho de callback e URI completa de redirecionamento
REDIRECT_PATH = "/auth/redirect"

# REDIRECT_URI dinâmico baseado no ambiente
# Em produção (Render), usa variável de ambiente ou detecta automaticamente
def get_redirect_uri():
    """
    Retorna a URI de redirecionamento baseada no ambiente.
    
    Prioridade:
    1. Variável de ambiente RENDER_EXTERNAL_URL (Render)
    2. Variável de ambiente REDIRECT_URI
    3. Request host (se disponível)
    4. Fallback para localhost em desenvolvimento
    """
    # Render define RENDER_EXTERNAL_URL automaticamente
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        return render_url.rstrip("/") + REDIRECT_PATH
    
    # Variável de ambiente customizada
    custom_uri = os.getenv("REDIRECT_URI")
    if custom_uri:
        return custom_uri.rstrip("/") + REDIRECT_PATH
    
    # Fallback para localhost em desenvolvimento
    return "http://localhost:5000" + REDIRECT_PATH

REDIRECT_URI = get_redirect_uri()

# Escopos de permissão que o app solicita (User.Read já é suficiente para pegar dados básicos)
SCOPE = ["User.Read"]

# Chave que usaremos para armazenar o usuário na sessão Flask
SESSION_USER_KEY = "user"


# ======================================================================
# FUNÇÕES AUXILIARES DE AUTENTICAÇÃO
# ======================================================================

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
    Usa sempre REDIRECT_URI, igual ao configurado no portal.
    Atualiza REDIRECT_URI dinamicamente antes de usar.
    """
    # Atualiza REDIRECT_URI se necessário (para produção)
    global REDIRECT_URI
    render_url = os.getenv("RENDER_EXTERNAL_URL")
    if render_url:
        REDIRECT_URI = render_url.rstrip("/") + REDIRECT_PATH
    
    return _build_msal_app().get_authorization_request_url(
        scopes or [],
        redirect_uri=REDIRECT_URI,
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
            return redirect(url_for("msal_login"))
        return view_func(*args, **kwargs)

    return wrapper


# ======================================================================
# FUNÇÃO DE SETUP PARA REGISTRAR ROTAS NO APP FLASK
# ======================================================================

def setup_msal_auth(app, redirect_uri=None):
    """
    Registra as rotas de autenticação Microsoft no app Flask.

    Args:
        app: Instância do Flask
        redirect_uri: URI de redirecionamento personalizada (opcional).
                     Se não fornecida, usa o padrão baseado em REDIRECT_PATH.

    Rotas registradas:
        - /login: Inicia o fluxo de autenticação
        - /auth/redirect: Callback da Microsoft após login
        - /logout: Remove o usuário da sessão

    Exemplo:
        app = Flask(__name__)
        setup_msal_auth(app)
    """
    global REDIRECT_URI
    
    if redirect_uri:
        REDIRECT_URI = redirect_uri
    else:
        # Atualiza REDIRECT_URI dinamicamente baseado no request context
        # Isso permite que funcione tanto em desenvolvimento quanto em produção
        @app.before_request
        def update_redirect_uri():
            global REDIRECT_URI
            from flask import request
            # Se estiver em produção e não tiver variável de ambiente, usa o host do request
            if not os.getenv("RENDER_EXTERNAL_URL") and not os.getenv("REDIRECT_URI"):
                if request.host_url:
                    scheme = "https" if request.is_secure else "http"
                    REDIRECT_URI = f"{scheme}://{request.host}{REDIRECT_PATH}"

    @app.route("/login")
    def msal_login():
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
    def msal_authorized():
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

        # Atualiza REDIRECT_URI se necessário (para produção)
        global REDIRECT_URI
        render_url = os.getenv("RENDER_EXTERNAL_URL")
        if render_url:
            REDIRECT_URI = render_url.rstrip("/") + REDIRECT_PATH
        elif not os.getenv("REDIRECT_URI"):
            # Usa o host do request como fallback
            scheme = "https" if request.is_secure else "http"
            REDIRECT_URI = f"{scheme}://{request.host}{REDIRECT_PATH}"

        # Troca o authorization code por tokens
        result = _build_msal_app().acquire_token_by_authorization_code(
            code,
            scopes=SCOPE,
            redirect_uri=REDIRECT_URI,
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
    def msal_logout():
        """
        Remove os dados do usuário da sessão (logout local do app).

        Obs.: isso não faz logout global da conta Microsoft no navegador,
        apenas "desloga" o usuário deste aplicativo Flask.
        """
        session.pop(SESSION_USER_KEY, None)
        flash("Você saiu do sistema.", "success")
        return redirect(url_for("index"))


# ======================================================================
# FUNÇÃO AUXILIAR PARA OBTER USUÁRIO DA SESSÃO
# ======================================================================

def get_current_user():
    """
    Retorna o dicionário com dados do usuário logado, ou None se não autenticado.
    
    Exemplo:
        user = get_current_user()
        if user:
            print(user.get('email'))
    """
    return session.get(SESSION_USER_KEY)

