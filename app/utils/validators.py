"""
Funções de validação.

Contém funções para validar dados de entrada.
"""

from app.config import Config


def allowed_file(filename: str) -> bool:
    """
    Verifica se o nome de arquivo possui uma extensão permitida.

    Regras:
    - Deve conter um ponto (.)
    - Tudo após o último ponto deve estar em ALLOWED_EXTENSIONS
    
    Args:
        filename: Nome do arquivo a validar
        
    Returns:
        True se a extensão for permitida, False caso contrário
    """
    return "." in filename and filename.rsplit(".", 1)[1].lower() in Config.ALLOWED_EXTENSIONS

