"""
Configurações centralizadas da aplicação Flask.

Centraliza todas as configurações, constantes e variáveis de ambiente.
"""

import os
import tempfile
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Configurações base da aplicação."""
    
    # Chave secreta para sessões Flask
    SECRET_KEY = os.getenv("FLASK_SECRET_KEY", os.urandom(24))
    
    # Limite de tamanho do upload: 100 MB
    MAX_CONTENT_LENGTH = 100 * 1024 * 1024
    
    # Pasta base para arquivos temporários
    UPLOAD_FOLDER = tempfile.gettempdir()
    
    # Extensões de arquivo permitidas para upload
    ALLOWED_EXTENSIONS = {"pdf"}


def get_config():
    """
    Retorna a classe de configuração.
    
    Returns:
        Classe Config com todas as configurações
    """
    return Config

