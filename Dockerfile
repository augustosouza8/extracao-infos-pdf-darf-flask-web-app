# 1. Usa uma imagem oficial do Python 3.12 (leve e compatível com seu runtime.txt)
FROM python:3.12-slim

# 2. Configura variáveis para otimizar o Python no Docker
# Impede criação de arquivos .pyc e garante que os logs apareçam no console da Azure
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 3. Define o diretório de trabalho dentro do container
WORKDIR /app

# 4. Instala dependências do sistema operacional necessárias para OCR e PDF
# (Necessário para o rapidocr-onnxruntime e opencv funcionarem no Linux slim)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 5. Copia o arquivo de dependências primeiro (para aproveitar o cache do Docker)
COPY requirements.txt .

# 6. Instala as bibliotecas do Python listadas no requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# 7. Copia todo o restante do código do seu projeto para dentro do container
COPY . .

# 8. Expõe a porta 5000 (padrão do Flask) para a Azure conseguir conversar com o container
EXPOSE 5000

# 9. Comando para iniciar sua aplicação (similar ao seu Procfile)
CMD ["gunicorn", "wsgi:app", "--bind", "0.0.0.0:5000", "--timeout", "3600"]