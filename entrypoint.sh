set -e

echo ">> [startup] inicializando banco (create_all + seed)..."
python -m scripts.init_db

echo ">> [startup] iniciando servidor..."
exec "$@"
