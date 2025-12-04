"""
Factory para criação da aplicação Flask.

Centraliza a criação e configuração do app Flask usando o padrão factory.
"""

from pathlib import Path
from flask import Flask

from app.config import Config
from app.routes import main, api


def create_app(config_class=Config):
    """
    Cria e configura a aplicação Flask.
    
    Args:
        config_class: Classe de configuração a usar
        
    Returns:
        Instância configurada do Flask app
    """
    # Define caminhos para templates e static files (na raiz do projeto)
    base_dir = Path(__file__).parent.parent
    template_folder = str(base_dir / "templates")
    static_folder = str(base_dir / "static")
    
    app = Flask(
        __name__,
        template_folder=template_folder,
        static_folder=static_folder,
    )
    
    # Aplica configurações
    config = config_class()
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
    app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
    
    # Registra blueprints
    app.register_blueprint(main.bp)
    app.register_blueprint(api.bp)
    
    return app


# Cria instância do app para compatibilidade com gunicorn app:app
# Isso permite que tanto wsgi:app quanto app:app funcionem
app = create_app()

