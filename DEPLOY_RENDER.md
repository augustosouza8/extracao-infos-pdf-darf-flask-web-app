# Instruções para Deploy no Render

Este documento contém todas as instruções necessárias para fazer deploy da aplicação no Render.

## Arquivos Criados/Modificados

### Arquivos Criados
- ✅ `requirements.txt` - Dependências do projeto
- ✅ `Procfile` - Comando de start para produção
- ✅ `runtime.txt` - Versão do Python (3.12.7)
- ✅ `render.yaml` - Configuração alternativa (opcional)

### Arquivos Modificados
- ✅ `app.py` - Ajustado para usar porta do ambiente e modo produção
- ✅ `config_db.py` - Configurado para usar volume persistente do Render
- ✅ `msal_auth.py` - REDIRECT_URI dinâmico baseado na URL do Render
- ✅ `pyproject.toml` - Versão do Python ajustada para >=3.11

## Passo a Passo no Render

### 1. Criar Novo Web Service

1. Acesse o [painel do Render](https://dashboard.render.com)
2. Clique em **"New +"** → **"Web Service"**
3. Conecte seu repositório GitHub:
   - Selecione o repositório: `augustosouza8/extracao-infos-pdf-darf-flask-web-app`
   - Branch: `main`
   - Root Directory: (deixe vazio se o projeto está na raiz)

### 2. Configurar Build & Deploy

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

### 3. Configurar Variáveis de Ambiente

No painel do Render, vá em **"Environment"** e adicione:

**Obrigatórias:**
- `FLASK_SECRET_KEY`: Gere uma chave secreta aleatória (ex: use `python -c "import secrets; print(secrets.token_hex(32))"`)

**Opcionais (se usar autenticação Microsoft):**
- `MS_CLIENT_ID`: ID do aplicativo no Microsoft Entra ID
- `MS_CLIENT_SECRET`: Secret do aplicativo
- `MS_TENANT_ID`: ID do tenant (ou "common")

**Automáticas (não precisa configurar):**
- `PORT`: Render define automaticamente
- `RENDER_EXTERNAL_URL`: Render define automaticamente com a URL do serviço

### 4. Configurar Volume Persistente (CRÍTICO)

**IMPORTANTE:** Sem volume persistente, o banco de dados `config.db` será perdido a cada restart/deploy!

1. No painel do Render, vá em **"Volumes"** (ou procure por "Persistent Disk")
2. Clique em **"Create Volume"**
3. Configure:
   - **Name**: `config-db-volume` (ou qualquer nome)
   - **Mount Path**: `/opt/render/project/src/data` (ou outro caminho de sua preferência)
   - **Size**: 1 GB é suficiente (mínimo)

4. **Após criar o volume**, adicione uma variável de ambiente:
   - `RENDER_VOLUME_PATH`: `/opt/render/project/src/data` (ou o caminho que você escolheu)

**Nota:** O código já está preparado para usar o volume. Se `RENDER_VOLUME_PATH` estiver definido, o banco será criado lá. Caso contrário, tentará usar `/opt/render/project/src/data` ou o diretório do projeto.

### 5. Configurar Microsoft Entra ID (se usar autenticação)

1. Acesse o [portal do Microsoft Entra ID](https://portal.azure.com)
2. Vá em **"App registrations"** → Seu aplicativo
3. Em **"Authentication"**, adicione um novo Redirect URI:
   - **Tipo**: Web
   - **URI**: `https://seu-app.onrender.com/auth/redirect`
   - Substitua `seu-app` pelo nome do seu serviço no Render

4. Salve as alterações

### 6. Deploy

1. Clique em **"Manual Deploy"** → **"Deploy latest commit"** (ou faça push para o GitHub para deploy automático)
2. Aguarde o build e deploy completarem
3. Verifique os logs para garantir que não há erros

## Verificações Pós-Deploy

### 1. Testar Acesso
- Acesse a URL do serviço (ex: `https://seu-app.onrender.com`)
- Verifique se a página carrega corretamente

### 2. Verificar Banco de Dados
- Acesse a seção "Gerenciar Regras"
- Tente adicionar um código ou CNPJ
- Verifique se os dados persistem após refresh

### 3. Testar Upload de PDF
- Faça upload de um PDF de teste
- Verifique se o processamento funciona
- Baixe o Excel gerado e verifique as abas

### 4. Verificar Persistência
- Adicione algumas regras
- Faça um restart manual do serviço no Render
- Verifique se as regras ainda estão lá após o restart

## Troubleshooting

### Erro: "Module not found"
- Verifique se todas as dependências estão no `requirements.txt`
- Verifique os logs de build

### Erro: "Port already in use"
- O Render define a porta automaticamente via `$PORT`
- Não configure porta manualmente

### Banco de dados não persiste
- Verifique se o volume persistente foi criado e montado corretamente
- Verifique se `RENDER_VOLUME_PATH` está configurado
- Verifique os logs para ver onde o banco está sendo criado

### Timeout ao processar PDF
- Render tem timeout de 30 segundos no plano gratuito
- PDFs grandes ou com OCR podem demorar mais
- Considere upgrade de plano ou otimização do processamento

### Erro de autenticação Microsoft
- Verifique se o Redirect URI no Microsoft Entra ID está correto
- Verifique se as variáveis de ambiente estão configuradas
- Verifique os logs para mensagens de erro específicas

## Limites do Plano Gratuito

- ⚠️ **Sleep após 15 minutos de inatividade**: O serviço "dorme" após 15 minutos sem requisições
- ⚠️ **Timeout de 30 segundos**: Requests que demoram mais de 30 segundos são cancelados
- ⚠️ **512 MB RAM**: Limite de memória
- ⚠️ **Build time limit**: Limite de tempo para builds

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
3. Verifique se o volume persistente está montado
4. Consulte a [documentação do Render](https://render.com/docs)

