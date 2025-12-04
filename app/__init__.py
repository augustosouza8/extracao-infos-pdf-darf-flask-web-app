"""
Factory para criação da aplicação Flask.

Centraliza a criação e configuração do app Flask usando o padrão factory.
"""

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
    app = Flask(__name__)
    
    # Aplica configurações
    config = config_class()
    app.secret_key = config.SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = config.MAX_CONTENT_LENGTH
    app.config["UPLOAD_FOLDER"] = config.UPLOAD_FOLDER
    
    # Registra blueprints
    app.register_blueprint(main.bp)
    app.register_blueprint(api.bp)
    
    return app

