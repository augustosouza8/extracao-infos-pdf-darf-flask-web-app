"""
Funções de formatação e limpeza de dados.

Centraliza todas as funções que formatam, limpam ou transformam strings.
"""

import re
from datetime import datetime, timedelta
from typing import Optional


def extrair_apenas_numeros(texto: str) -> str:
    """
    Extrai apenas os dígitos numéricos de uma string.
    
    Args:
        texto: String que pode conter números e outros caracteres
        
    Returns:
        String contendo apenas dígitos
    """
    if not texto:
        return ""
    return re.sub(r"\D", "", str(texto))


def calcular_data_menos_um_dia(data_str: str) -> str:
    """
    Subtrai 1 dia de uma data no formato DD/MM/AAAA.
    
    Args:
        data_str: Data no formato DD/MM/AAAA
        
    Returns:
        Data com 1 dia a menos no formato DD/MM/AAAA, ou string vazia se inválida
    """
    if not data_str:
        return ""
    
    try:
        # Tenta parsear a data
        data = datetime.strptime(data_str.strip(), "%d/%m/%Y")
        data_menos_um = data - timedelta(days=1)
        return data_menos_um.strftime("%d/%m/%Y")
    except (ValueError, AttributeError):
        return ""


def calcular_mes_anterior() -> str:
    """
    Calcula o mês anterior à data atual no formato MM/AAAA.
    
    Returns:
        String no formato MM/AAAA do mês anterior
    """
    hoje = datetime.now()
    # Se for janeiro, o mês anterior é dezembro do ano anterior
    if hoje.month == 1:
        mes_anterior = 12
        ano_anterior = hoje.year - 1
    else:
        mes_anterior = hoje.month - 1
        ano_anterior = hoje.year
    
    return f"{mes_anterior:02d}/{ano_anterior}"


def limpar_valor_monetario(valor: str) -> str:
    """
    Remove pontos e vírgulas de um valor monetário.
    Ex: "1.386,00" -> "138600"
    
    Args:
        valor: String com valor monetário formatado
        
    Returns:
        String apenas com dígitos
    """
    if not valor:
        return ""
    return str(valor).replace(".", "").replace(",", "")


def limpar_cnpj(cnpj: str) -> str:
    """
    Remove pontos, barras e hífens de um CNPJ.
    Ex: "29.979.036/0001-40" -> "29979036000140"
    
    Args:
        cnpj: String com CNPJ formatado
        
    Returns:
        String apenas com dígitos
    """
    if not cnpj:
        return ""
    return str(cnpj).replace(".", "").replace("/", "").replace("-", "")


def limpar_mes_ano(mes_ano: str) -> str:
    """
    Remove a barra de um valor mês/ano.
    Ex: "11/2025" -> "112025"
    
    Args:
        mes_ano: String no formato MM/AAAA
        
    Returns:
        String apenas com dígitos
    """
    if not mes_ano:
        return ""
    return str(mes_ano).replace("/", "")


def limpar_data(data: str) -> str:
    """
    Remove as barras de uma data.
    Ex: "19/10/2025" -> "19102025"
    
    Args:
        data: String no formato DD/MM/AAAA
        
    Returns:
        String apenas com dígitos
    """
    if not data:
        return ""
    return str(data).replace("/", "")

