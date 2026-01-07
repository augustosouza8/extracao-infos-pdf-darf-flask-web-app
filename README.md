# Extrator de Informações DARF

Aplicação Flask para extrair informações de PDFs de DARF e gerar arquivos Excel consolidados (com abas **servidor**, **patronal-gilrat** e **erros**).

---

## Estrutura do Projeto

```
.
├── app/                    # Aplicação Flask
│   ├── static/             # Arquivos estáticos (CSS, JS, imagens)
│   ├── templates/          # Templates HTML
│   ├── routes/             # Rotas da aplicação (main + API de regras)
│   ├── services/           # Serviços (parser de PDF, geração de Excel)
│   ├── utils/              # Utilitários (formatters, validators, errors)
│   ├── models.py           # Modelos SQLAlchemy
│   ├── database/           # Regras e dados padrão (CODIGOS_PADRAO/CNPJS_PADRAO)
│   └── config.py           # Configurações
├── migrations/             # Migrations do banco (Flask-Migrate), quando aplicável
├── scripts/
│   └── init_db.py          # Inicialização/seed automática do banco no startup
├── entrypoint.sh           # EntryPoint do container (roda init_db e inicia Gunicorn)
├── Dockerfile              # Build do container (Azure App Service for Containers)
├── wsgi.py                 # Ponto de entrada WSGI
├── parse_darf.py           # (legado) processamento de PDFs / utilitário
└── requirements.txt        # Dependências Python
```

---

## Configuração Local

1. Instale as dependências:
   ```bash
   uv sync
   # ou
   pip install -r requirements.txt
   ```

2. Copie o `.env.example` para `.env` e defina:
   - `FLASK_SECRET_KEY`: qualquer valor secreto aleatório (não compartilhe).
   - `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID`: dados do aplicativo configurado no Microsoft Entra ID.
   - `DATABASE_URL`: (opcional) URL do PostgreSQL. Se não definido, usa SQLite local (arquivo `config.db`).

3. No portal do Entra ID configure o Redirect URI para `http://localhost:5000/auth/redirect`.  
   O app Flask usa exatamente esse valor internamente, então ele precisa coincidir.

4. Inicialize o banco de dados (opcional em dev):
   ```bash
   flask db upgrade
   flask init-db
   ```

---

## Execução Local

1. Exporte as variáveis do `.env` (caso sua ferramenta não faça isso automaticamente).  
   Com `python-dotenv`, basta manter o arquivo na raiz.

2. Rode o servidor de desenvolvimento:
   ```bash
   uv run flask --app wsgi run --host 0.0.0.0 --port 5000
   # ou
   python wsgi.py
   ```

3. Acesse `http://localhost:5000/`. A autenticação Microsoft redirecionará para `http://localhost:5000/auth/redirect`.

---

## Deploy na Azure (App Service for Containers)

### Visão geral (atualizado)

A aplicação é executada em container usando `Dockerfile` + `entrypoint.sh`.

No **startup do container**, o `entrypoint.sh` executa:
1. `python -m scripts.init_db` (cria tabelas e popula dados padrão)
2. inicia o Gunicorn (`wsgi:app`)

Isso elimina a necessidade de entrar via SSH para executar `flask init-db` manualmente após o deploy.

> **Nota sobre migrations:** se você estiver usando Flask-Migrate/Alembic em produção, mantenha `flask db upgrade` no seu pipeline (ou adapte `scripts/init_db.py` para executar migrations antes do seed). O seed padrão é idempotente e só insere valores quando as tabelas estão vazias.

### Pré-requisitos

- Azure App Service for Containers
- Banco PostgreSQL (Azure Database for PostgreSQL, Render, etc.)
- Aplicativo registrado no Microsoft Entra ID

### Variáveis de Ambiente na Azure

Configure as seguintes variáveis de ambiente no Azure App Service (Configuration → Application settings):

1. **WEBSITES_PORT**: `5000`  
   (necessário porque o container escuta em `0.0.0.0:5000`)

2. **FLASK_SECRET_KEY**: chave secreta para sessões Flask (gere um valor aleatório seguro)

3. **DATABASE_URL**: URL de conexão PostgreSQL no formato:
   ```
   postgresql://usuario:senha@host:porta/nome_banco
   ```
   - Se você estiver usando o Render, utilize a **External Database URL**.
   - Se a plataforma fornecer `postgres://`, o app converte automaticamente para `postgresql://`.

4. **MS_CLIENT_ID**, **MS_CLIENT_SECRET**, **MS_TENANT_ID**: credenciais do Microsoft Entra ID.

### Configuração do Microsoft Entra ID

No portal do Microsoft Entra ID, configure o Redirect URI para:
```
https://seu-app.azurewebsites.net/auth/redirect
```

### Deploy via Docker (local → Azure)

```bash
# Build da imagem
docker build -t extracao-darf .

# Teste local (use DATABASE_URL real se quiser testar Postgres)
docker run -p 5000:5000 -e FLASK_SECRET_KEY=test -e WEBSITES_PORT=5000 extracao-darf
```

### Deploy via GitHub (App Service)

1. Conecte o App Service ao seu repositório (Deployment Center).
2. O Azure fará o build e o deploy do container com base no `Dockerfile`.
3. No primeiro start, o `entrypoint.sh` fará a criação/seed do banco automaticamente.

---

## Banco de Dados: seed e regras

### Seed automático
O `scripts/init_db.py` cria as tabelas (quando necessário) e executa o seed com os valores padrão:
- `CODIGOS_PADRAO`: mapeamento **código → aba** (servidor/patronal-gilrat)
- `CNPJS_PADRAO`: mapeamento **CNPJ → UO Contribuinte**

**Importante:** o seed padrão só insere quando a tabela está vazia (não “completa” itens faltantes se já existir algo).

### Atualizar regras em produção
O sistema expõe endpoints para gerenciar regras (códigos/CNPJ) via API. Em produção, recomenda-se proteger esses endpoints (por autenticação ou restrição de rede).

---

## Suporte a PDFs Escaneados (OCR)

O sistema suporta tanto PDFs com texto nativo quanto PDFs escaneados (imagens):

- **PDFs com texto nativo**: o texto é extraído diretamente usando `pdfplumber`.
- **PDFs escaneados**: quando o texto extraído é insuficiente, o sistema usa OCR com `RapidOCR-onnxruntime`.

---

## Tecnologias Utilizadas

- **Flask**: framework web
- **Flask-SQLAlchemy**: ORM
- **Flask-Migrate**: migrations (quando aplicável)
- **PostgreSQL/SQLite**: banco de dados
- **pdfplumber**: extração de texto de PDFs
- **RapidOCR-onnxruntime**: OCR
- **pandas/openpyxl**: geração de Excel
- **MSAL**: autenticação Microsoft

---

## Observações

- Em produção, use PostgreSQL (SQLite dentro do container pode ser efêmero conforme a configuração do App Service).
- Garanta que o `.env` não seja versionado (já contemplado no `.gitignore`).
