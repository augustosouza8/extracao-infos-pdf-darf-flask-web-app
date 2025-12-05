# Extrator de Informações DARF

Aplicação Flask para extrair informações de PDFs de DARF e gerar arquivos Excel consolidados.

## Estrutura do Projeto

```
.
├── app/                    # Aplicação Flask
│   ├── static/            # Arquivos estáticos (CSS, JS, imagens)
│   ├── templates/         # Templates HTML
│   ├── routes/            # Rotas da aplicação
│   ├── services/          # Serviços (geração de Excel)
│   ├── utils/             # Utilitários (formatters, validators, errors)
│   ├── models.py          # Modelos SQLAlchemy
│   └── config.py          # Configurações
├── migrations/             # Migrations do banco de dados (Flask-Migrate)
├── wsgi.py                # Ponto de entrada WSGI
├── config_db.py           # Gerenciamento do banco de dados
├── parse_darf.py          # Processamento de PDFs
└── requirements.txt       # Dependências Python
```

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
   - `DATABASE_URL`: (opcional) URL do PostgreSQL. Se não definido, usa SQLite local (`config.db`).

3. No portal do Entra ID configure o Redirect URI para `http://localhost:5000/auth/redirect`. O app Flask usa exatamente esse valor internamente (`REDIRECT_URI`), então ele precisa coincidir.

4. Inicialize o banco de dados:
   ```bash
   flask db upgrade
   flask init-db
   ```

## Execução Local

1. Exporte as variáveis do `.env` (caso sua ferramenta não faça isso automaticamente). Com `python-dotenv`, basta manter o arquivo na raiz.

2. Rode o servidor de desenvolvimento:
   ```bash
   uv run flask --app wsgi run --host 0.0.0.0 --port 5000
   # ou
   python wsgi.py
   ```

3. Acesse `http://localhost:5000/`. A autenticação Microsoft redirecionará para `http://localhost:5000/auth/redirect`, evitando erros AADSTS900971.

## Deploy na Azure

### Pré-requisitos

- Conta Azure com Azure App Service configurado
- Azure Database for PostgreSQL (ou outro banco PostgreSQL)
- Aplicativo registrado no Microsoft Entra ID

### Variáveis de Ambiente na Azure

Configure as seguintes variáveis de ambiente no Azure App Service:

1. **FLASK_SECRET_KEY**: Chave secreta para sessões Flask (gerar valor aleatório seguro)
2. **DATABASE_URL**: URL de conexão do PostgreSQL no formato:
   ```
   postgresql://usuario:senha@servidor:porta/nome_banco
   ```
   Nota: Se a Azure fornecer `postgres://`, será automaticamente convertido para `postgresql://`.

3. **MS_CLIENT_ID**: ID do aplicativo no Microsoft Entra ID
4. **MS_CLIENT_SECRET**: Secret do aplicativo no Microsoft Entra ID
5. **MS_TENANT_ID**: ID do tenant do Microsoft Entra ID

### Configuração do Microsoft Entra ID

No portal do Microsoft Entra ID, configure o Redirect URI para:
```
https://seu-app.azurewebsites.net/auth/redirect
```

### Deploy via Docker

O projeto inclui um `Dockerfile` otimizado para Azure:

```bash
# Build da imagem
docker build -t extracao-darf .

# Teste local
docker run -p 5000:5000 -e FLASK_SECRET_KEY=test extracao-darf

# Push para Azure Container Registry (exemplo)
az acr build --registry seu-registry --image extracao-darf:latest .
```

### Deploy via Git

1. Configure o Azure App Service para fazer deploy do repositório Git
2. O Azure executará automaticamente o build baseado no `Dockerfile`
3. Após o deploy, execute as migrations:
   ```bash
   az webapp ssh --name seu-app --resource-group seu-resource-group
   flask db upgrade
   flask init-db
   ```

### Migrations do Banco de Dados

O projeto usa Flask-Migrate para gerenciar mudanças no schema do banco:

```bash
# Criar nova migration
flask db migrate -m "Descrição da mudança"

# Aplicar migrations
flask db upgrade

# Reverter última migration
flask db downgrade
```

**Importante**: Após o primeiro deploy na Azure, execute:
```bash
flask db upgrade  # Cria as tabelas
flask init-db    # Popula dados padrão
```

### Comandos Úteis

- `flask init-db`: Inicializa o banco e popula com dados padrão
- `flask db upgrade`: Aplica todas as migrations pendentes
- `flask db migrate -m "mensagem"`: Cria nova migration baseada em mudanças nos modelos

## Observações

- Os PDFs enviados são processados por `parse_darf.py` e geram um Excel consolidado baixado via navegador.
- Garanta que o `.env` não seja versionado (já está contemplado no `.gitignore`).
- O banco de dados local (SQLite) é usado apenas para desenvolvimento. Em produção, use PostgreSQL.

## Suporte a PDFs Escaneados (OCR)

O sistema suporta tanto PDFs com texto nativo quanto PDFs escaneados (imagens):

- **PDFs com texto nativo**: O texto é extraído diretamente usando `pdfplumber`, que é rápido e preciso.
- **PDFs escaneados**: Quando o texto extraído é insuficiente (< 100 caracteres), o sistema usa automaticamente OCR (Reconhecimento Óptico de Caracteres) com `RapidOCR-onnxruntime` para extrair o texto das imagens.

O processamento com OCR é mais lento que a extração de texto nativo, mas permite processar documentos escaneados. O `RapidOCR-onnxruntime` é mais rápido que o PaddleOCR (4-5x) e não requer binários externos, funcionando apenas com `pip install`. Os modelos são baixados automaticamente na primeira execução.

## Tecnologias Utilizadas

- **Flask**: Framework web
- **Flask-SQLAlchemy**: ORM para banco de dados
- **Flask-Migrate**: Gerenciamento de migrations
- **PostgreSQL/SQLite**: Banco de dados
- **pdfplumber**: Extração de texto de PDFs
- **RapidOCR-onnxruntime**: OCR para PDFs escaneados
- **pandas/openpyxl**: Geração de arquivos Excel
- **MSAL**: Autenticação Microsoft
