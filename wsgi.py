"""
Ponto de entrada WSGI da aplicação Flask.

Este arquivo é usado pelo gunicorn (wsgi:app) e serve
como ponto de entrada para a aplicação em produção.
"""

import os
from app import create_app

# Cria a aplicação usando o factory
app = create_app()

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
    # Em produção, o Render usa gunicorn e define a porta via variável PORT
    # Em desenvolvimento, usa porta 5000
    port = int(os.getenv("PORT", 5000))
    debug = os.getenv("FLASK_ENV") != "production"
    app.run(debug=debug, host="0.0.0.0", port=port)
