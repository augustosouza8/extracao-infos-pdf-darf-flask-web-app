## Configuração

1. Instale as dependências:
   ```bash
   uv sync
   # ou
   poetry install
   ```
2. Copie o `.env.example` para `.env` e defina:
   - `FLASK_SECRET_KEY`: qualquer valor secreto aleatório (não compartilhe).
   - `MS_CLIENT_ID`, `MS_CLIENT_SECRET`, `MS_TENANT_ID`: dados do aplicativo configurado no Microsoft Entra ID.
3. No portal do Entra ID configure o Redirect URI para `http://localhost:5000/auth/redirect`. O app Flask usa exatamente esse valor internamente (`REDIRECT_URI`), então ele precisa coincidir.

## Execução

1. Exporte as variáveis do `.env` (caso sua ferramenta não faça isso automaticamente). Com `python-dotenv`, basta manter o arquivo na raiz.
2. Rode o servidor de desenvolvimento:
   ```bash
   uv run flask --app app run --host 0.0.0.0 --port 5000
   # ou
   poetry run flask --app app run --host 0.0.0.0 --port 5000
   ```
3. Acesse sempre `http://localhost:5000/`. A autenticação Microsoft redirecionará para `http://localhost:5000/auth/redirect`, evitando erros AADSTS900971.

## Observações

- Os PDFs enviados são processados por `parse_darf.py` e geram um Excel consolidado baixado via navegador.
- Garanta que o `.env` não seja versionado (já está contemplado no `.gitignore`).

## Suporte a PDFs Escaneados (OCR)

O sistema suporta tanto PDFs com texto nativo quanto PDFs escaneados (imagens):

- **PDFs com texto nativo**: O texto é extraído diretamente usando `pdfplumber`, que é rápido e preciso.
- **PDFs escaneados**: Quando o texto extraído é insuficiente (< 100 caracteres), o sistema usa automaticamente OCR (Reconhecimento Óptico de Caracteres) com `RapidOCR-onnxruntime` para extrair o texto das imagens.

O processamento com OCR é mais lento que a extração de texto nativo, mas permite processar documentos escaneados. O `RapidOCR-onnxruntime` é mais rápido que o PaddleOCR (4-5x) e não requer binários externos, funcionando apenas com `pip install`. Os modelos são baixados automaticamente na primeira execução.