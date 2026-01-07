import os
import time

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app import create_app, db
from app.database.default_data import init_db_data  # ajuste o import se o nome do arquivo for diferente

LOCK_ID = 924501  # qualquer inteiro fixo serve (use um "id do projeto")

def wait_for_db(max_tries=30, sleep_s=2):
    for i in range(max_tries):
        try:
            db.session.execute(text("SELECT 1"))
            return
        except OperationalError:
            time.sleep(sleep_s)
    raise RuntimeError("DB não ficou disponível a tempo.")

def is_postgres():
    uri = str(db.engine.url)
    return uri.startswith("postgresql")

def main():
    app = create_app()
    with app.app_context():
        wait_for_db()

        # Em Postgres: lock para evitar duas instâncias seed/migrate ao mesmo tempo
        if is_postgres():
            db.session.execute(text("SELECT pg_advisory_lock(:id)"), {"id": LOCK_ID})
            db.session.commit()

        try:
            # 1) Cria tabelas (útil para SQLite; em Postgres prefira migrations)
            db.create_all()

            # 2) Popula defaults (CODIGOS_PADRAO / CNPJS_PADRAO)
            init_db_data()

        finally:
            if is_postgres():
                db.session.execute(text("SELECT pg_advisory_unlock(:id)"), {"id": LOCK_ID})
                db.session.commit()

if __name__ == "__main__":
    main()
