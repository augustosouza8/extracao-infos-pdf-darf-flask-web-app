# Instruções para Deploy no Render

Este documento contém todas as instruções necessárias para fazer deploy da aplicação no Render usando PostgreSQL (plano gratuito).

## Arquivos Criados/Modificados

### Arquivos Criados
- ✅ `requirements.txt` - Dependências do projeto (inclui SQLAlchemy e psycopg2)
- ✅ `Procfile` - Comando de start para produção
- ✅ `runtime.txt` - Versão do Python (3.12.7)
- ✅ `render.yaml` - Configuração alternativa (opcional)

### Arquivos Modificados
- ✅ `app.py` - Ajustado para usar porta do ambiente (PORT) e modo produção
- ✅ `config_db.py` - Refatorado para usar SQLAlchemy com PostgreSQL (produção) e SQLite (desenvolvimento)
- ✅ `msal_auth.py` - REDIRECT_URI dinâmico baseado na URL do Render
- ✅ `pyproject.toml` - Versão do Python ajustada para >=3.11

## Passo a Passo no Render

### 1. Criar Banco de Dados PostgreSQL

1. Acesse o [painel do Render](https://dashboard.render.com)
2. Clique em **"New +"** → **"PostgreSQL"**
3. Configure:
   - **Name**: `extracao-darf-db` (ou qualquer nome)
   - **Database**: (deixe o padrão ou escolha um nome)
   - **User**: (deixe o padrão ou escolha um nome)
   - **Region**: Escolha a região mais próxima
   - **PostgreSQL Version**: Deixe a versão mais recente
   - **Plan**: **Free** (plano gratuito)
4. Clique em **"Create Database"**
5. Aguarde a criação do banco (pode levar alguns minutos)

### 2. Obter INTERNAL_DATABASE_URL

1. Após o banco ser criado, acesse o painel do banco de dados
2. Na seção **"Connections"**, você verá:
   - **Internal Database URL**: Algo como `postgresql://user:password@hostname:5432/dbname`
3. **Copie a INTERNAL_DATABASE_URL** (você precisará dela no próximo passo)

**Importante:** Use a **INTERNAL_DATABASE_URL**, não a External Database URL. A Internal funciona apenas dentro da rede do Render e é mais segura.

### 3. Criar Web Service

1. No painel do Render, clique em **"New +"** → **"Web Service"**
2. Conecte seu repositório GitHub:
   - Selecione o repositório: `augustosouza8/extracao-infos-pdf-darf-flask-web-app`
   - Branch: `main`
   - Root Directory: (deixe vazio se o projeto está na raiz)

### 4. Configurar Build & Deploy

**Python Version:**
- O arquivo `runtime.txt` especifica Python 3.12.7
- **IMPORTANTE**: O Render pode usar Python 3.13 automaticamente, mas `rapidocr-onnxruntime` não suporta Python 3.13
- **Solução**: Nas configurações do serviço (Settings → Environment), adicione uma variável de ambiente:
  - **Key**: `PYTHON_VERSION`
  - **Value**: `3.12.7`
- Ou use o `render.yaml` que já está configurado com `runtime: python-3.12.7`

**Build Command:**
```
pip install -r requirements.txt
```

**Start Command:**
```
gunicorn app:app --bind 0.0.0.0:$PORT
```

**OU** use o `Procfile` (Render detecta automaticamente):
- Se o `Procfile` estiver presente, o Render usará automaticamente o comando definido nele

**Nota sobre Python 3.13:**
- Se você ver erros como "No matching distribution found for rapidocr-onnxruntime>=1.3.0", o Render está usando Python 3.13
- **Solução rápida**: Nas configurações do serviço, adicione `PYTHON_VERSION=3.12.7` nas variáveis de ambiente
- Ou use o `render.yaml` que força Python 3.12.7

### 5. Configurar Variáveis de Ambiente

No painel do Web Service, vá em **"Environment"** e adicione:

**Obrigatórias:**
- `FLASK_SECRET_KEY`: Gere uma chave secreta aleatória
  - No terminal: `python -c "import secrets; print(secrets.token_hex(32))"`
  - Ou use qualquer string aleatória longa

- `DATABASE_URL`: Cole a **INTERNAL_DATABASE_URL** que você copiou do banco PostgreSQL
  - Formato: `postgresql://user:password@hostname:5432/dbname`
  - O código automaticamente converte `postgres://` para `postgresql://` se necessário

**Opcionais (se usar autenticação Microsoft):**
- `MS_CLIENT_ID`: ID do aplicativo no Microsoft Entra ID
- `MS_CLIENT_SECRET`: Secret do aplicativo
- `MS_TENANT_ID`: ID do tenant (ou "common")

**Automáticas (não precisa configurar):**
- `PORT`: Render define automaticamente
- `RENDER_EXTERNAL_URL`: Render define automaticamente com a URL do serviço

### 6. Conectar Web Service ao Banco de Dados

1. No painel do **Web Service**, vá em **"Settings"**
2. Na seção **"Connections"**, clique em **"Connect"** ao lado do banco PostgreSQL criado
3. Isso garante que o Web Service tenha acesso ao banco na mesma rede interna

**Nota:** Após conectar, o Render pode criar automaticamente uma variável `DATABASE_URL` com a Internal Database URL. Verifique se ela está configurada corretamente.

### 7. Configurar Microsoft Entra ID (se usar autenticação)

1. Acesse o [portal do Microsoft Entra ID](https://portal.azure.com)
2. Vá em **"App registrations"** → Seu aplicativo
3. Em **"Authentication"**, adicione um novo Redirect URI:
   - **Tipo**: Web
   - **URI**: `https://seu-app.onrender.com/auth/redirect`
   - Substitua `seu-app` pelo nome do seu serviço no Render
4. Salve as alterações

### 8. Deploy

1. Clique em **"Manual Deploy"** → **"Deploy latest commit"** (ou faça push para o GitHub para deploy automático)
2. Aguarde o build e deploy completarem
3. Verifique os logs para garantir que não há erros
4. O banco de dados será criado automaticamente na primeira execução

## Como Funciona

### Desenvolvimento Local
- Se `DATABASE_URL` não estiver definida, o sistema usa SQLite local (`config.db`)
- Funciona normalmente para desenvolvimento e testes

### Produção no Render
- Se `DATABASE_URL` estiver definida, o sistema usa PostgreSQL
- As tabelas são criadas automaticamente na primeira execução
- Valores padrão são inseridos automaticamente se as tabelas estiverem vazias
- Dados persistem entre restarts e deploys

## Verificações Pós-Deploy

### 1. Testar Acesso
- Acesse a URL do serviço (ex: `https://seu-app.onrender.com`)
- Verifique se a página carrega corretamente

### 2. Verificar Banco de Dados
- Acesse a seção "Gerenciar Regras"
- Verifique se as regras padrão aparecem (códigos 1082, 1099, 1138, 1646 e CNPJs)
- Tente adicionar um código ou CNPJ
- Verifique se os dados persistem após refresh

### 3. Testar Upload de PDF
- Faça upload de um PDF de teste
- Verifique se o processamento funciona
- Baixe o Excel gerado e verifique as abas (servidor, patronal-gilrat, erros)

### 4. Verificar Persistência
- Adicione algumas regras
- Faça um restart manual do serviço no Render
- Verifique se as regras ainda estão lá após o restart

## Troubleshooting

### Erro: "Module not found" ou "No matching distribution found"
- Verifique se todas as dependências estão no `requirements.txt`
- Verifique os logs de build
- Se o erro for com `rapidocr-onnxruntime`, verifique se o Python está na versão 3.12 (não 3.13)
- O `runtime.txt` especifica Python 3.12.7, mas o Render pode usar 3.13 automaticamente
- **Solução**: Nas configurações do serviço (Settings → Environment), force Python 3.12

### Erro: "Port already in use"
- O Render define a porta automaticamente via `$PORT`
- Não configure porta manualmente

### Erro: "Could not connect to database"
- Verifique se `DATABASE_URL` está configurada corretamente
- Verifique se o Web Service está conectado ao banco PostgreSQL
- Use a **INTERNAL_DATABASE_URL**, não a External
- Verifique os logs para mensagens de erro específicas

### Erro: "relation does not exist" ou "table does not exist"
- O banco é criado automaticamente na primeira execução
- Verifique os logs para ver se há erros na criação das tabelas
- Tente fazer um restart do serviço

### Timeout ao processar PDF
- Render tem timeout de 30 segundos no plano gratuito
- PDFs grandes ou com OCR podem demorar mais
- Considere upgrade de plano ou otimização do processamento

### Erro de autenticação Microsoft
- Verifique se o Redirect URI no Microsoft Entra ID está correto
- Verifique se as variáveis de ambiente estão configuradas
- Verifique os logs para mensagens de erro específicas

## Limites do Plano Gratuito

### Web Service
- ⚠️ **Sleep após 15 minutos de inatividade**: O serviço "dorme" após 15 minutos sem requisições
- ⚠️ **Timeout de 30 segundos**: Requests que demoram mais de 30 segundos são cancelados
- ⚠️ **512 MB RAM**: Limite de memória
- ⚠️ **Build time limit**: Limite de tempo para builds

### PostgreSQL (Free)
- ✅ **90 dias de retenção**: Dados são mantidos por 90 dias
- ✅ **Sem limite de conexões**: Pode conectar múltiplos serviços
- ✅ **Backup automático**: Backups automáticos incluídos
- ⚠️ **1 GB de armazenamento**: Limite de espaço (suficiente para este projeto)

## Estrutura do Banco de Dados

O banco PostgreSQL terá duas tabelas:

### `codigo_aba`
- `codigo` (VARCHAR, PRIMARY KEY)
- `aba` (VARCHAR, CHECK: 'servidor' ou 'patronal-gilrat')

### `cnpj_uo`
- `cnpj` (VARCHAR, PRIMARY KEY)
- `uo_contribuinte` (VARCHAR)

## Próximos Passos

Após o deploy bem-sucedido:
1. Teste todas as funcionalidades
2. Configure domínio customizado (opcional)
3. Configure monitoramento e alertas (opcional)
4. Considere upgrade de plano se necessário

## Suporte

Em caso de problemas:
1. Verifique os logs no painel do Render
2. Verifique as variáveis de ambiente
3. Verifique se o Web Service está conectado ao banco PostgreSQL
4. Consulte a [documentação do Render](https://render.com/docs)
