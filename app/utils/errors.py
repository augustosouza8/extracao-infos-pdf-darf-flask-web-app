"""
Funções de coleta e formatação de erros.

Centraliza a lógica de coleta, categorização e formatação de erros
para a aba de erros do Excel.
"""

from app.database import get_aba_por_codigo, get_uo_por_cnpj


def coletar_erros_registro(registro: dict) -> list[dict]:
    """
    Coleta todos os erros de um registro processado.
    
    Args:
        registro: Dicionário com campos extraídos e mensagens de erro
        
    Returns:
        Lista de dicionários com informações de erro estruturadas
    """
    erros = []
    arquivo = registro.get("arquivo", "Desconhecido")
    
    # Mapeamento de campos e seus erros correspondentes
    campos_erro = [
        ("cnpj", "cnpj_erro", "CNPJ"),
        ("razao_social", "razao_social_erro", "Razão Social"),
        ("periodo_apuracao", "periodo_apuracao_erro", "Período de Apuração"),
        ("data_vencimento", "data_vencimento_erro", "Data de Vencimento"),
        ("numero_documento", "numero_documento_erro", "Número do Documento"),
        ("valor_total_documento", "valor_total_documento_erro", "Valor Total do Documento"),
        ("codigo", "codigo_erro", "Código"),
        ("denominacao", "denominacao_erro", "Denominação"),
        ("linha_digitavel", "linha_digitavel_erro", "Linha Digitável"),
    ]
    
    # Coleta erros de campos individuais
    for campo, campo_erro, nome_campo in campos_erro:
        valor = registro.get(campo)
        erro = registro.get(campo_erro)
        
        if erro:
            # Determina tipo de erro baseado na mensagem
            erro_lower = erro.lower()
            tipo_erro = "Extração"
            severidade = "Crítico"
            
            if "inválido" in erro_lower or "formato" in erro_lower or "dígitos verificadores" in erro_lower:
                tipo_erro = "Validação"
                severidade = "Crítico"
            elif "não encontrado" in erro_lower or "não encontrada" in erro_lower:
                tipo_erro = "Extração"
                severidade = "Crítico"
            elif "pdf vazio" in erro_lower or "erro geral" in erro_lower or "erro ao processar" in erro_lower:
                tipo_erro = "Processamento"
                severidade = "Crítico"
            elif "ocr" in erro_lower or "texto insuficiente" in erro_lower:
                tipo_erro = "Processamento"
                severidade = "Aviso"
            
            erros.append({
                "arquivo": arquivo,
                "campo": nome_campo,
                "tipo_erro": tipo_erro,
                "mensagem": erro,
                "valor_extraido": str(valor) if valor is not None else "",
                "severidade": severidade,
            })
    
    # Verifica erros de mapeamento
    codigo = registro.get("codigo")
    if codigo and not registro.get("codigo_erro"):
        # Código foi extraído com sucesso, mas verifica se está mapeado
        aba = get_aba_por_codigo(codigo)
        if not aba:
            erros.append({
                "arquivo": arquivo,
                "campo": "Código",
                "tipo_erro": "Mapeamento",
                "mensagem": f"Código '{codigo}' extraído mas não mapeado para nenhuma aba (servidor ou patronal-gilrat)",
                "valor_extraido": codigo,
                "severidade": "Aviso",
            })
    
    cnpj = registro.get("cnpj")
    if cnpj and not registro.get("cnpj_erro"):
        # CNPJ foi extraído com sucesso, mas verifica se tem UO mapeada
        uo = get_uo_por_cnpj(cnpj)
        if not uo:
            erros.append({
                "arquivo": arquivo,
                "campo": "CNPJ",
                "tipo_erro": "Mapeamento",
                "mensagem": f"CNPJ '{cnpj}' extraído mas não possui UO Contribuinte mapeada",
                "valor_extraido": cnpj,
                "severidade": "Aviso",
            })
    
    return erros


def formatar_linha_erro(erro: dict) -> dict:
    """
    Formata um erro para a aba de erros do Excel.
    
    Args:
        erro: Dicionário com informações de erro
        
    Returns:
        Dicionário formatado para a aba de erros
    """
    return {
        "Arquivo": erro.get("arquivo", ""),
        "Campo": erro.get("campo", ""),
        "Tipo de Erro": erro.get("tipo_erro", ""),
        "Mensagem": erro.get("mensagem", ""),
        "Valor Extraído": erro.get("valor_extraido", ""),
        "Severidade": erro.get("severidade", ""),
    }

