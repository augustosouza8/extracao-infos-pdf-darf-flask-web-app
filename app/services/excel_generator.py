"""
Serviço de geração de arquivos Excel.

Centraliza a lógica de formatação de registros e geração de arquivos Excel
com múltiplas abas (servidor, patronal-gilrat, erros).
"""

from pathlib import Path
from typing import List

import pandas as pd

from app.utils.formatters import (
    extrair_apenas_numeros,
    calcular_data_menos_um_dia,
    calcular_mes_anterior,
    limpar_valor_monetario,
    limpar_cnpj,
    limpar_mes_ano,
    limpar_data,
)
from app.utils.errors import coletar_erros_registro, formatar_linha_erro
from app.database import get_uo_por_cnpj


def formatar_linha_patronal_gilrat(registro: dict) -> dict:
    """
    Formata um registro para a aba "patronal-gilrat".
    
    Args:
        registro: Dicionário com campos extraídos do PDF
        
    Returns:
        Dicionário com colunas formatadas para a aba patronal-gilrat
    """
    arquivo = registro.get("arquivo", "") or ""
    cnpj = registro.get("cnpj", "") or ""
    numero_doc = registro.get("numero_documento", "") or ""
    linha_dig = registro.get("linha_digitavel", "") or ""
    valor_total = registro.get("valor_total_documento", "") or ""
    data_venc = registro.get("data_vencimento", "") or ""
    
    uo_contribuinte = get_uo_por_cnpj(cnpj) or ""
    nr_doc_numeros = extrair_apenas_numeros(numero_doc)
    codigo_barras_numeros = extrair_apenas_numeros(linha_dig)
    data_pagamento = calcular_data_menos_um_dia(data_venc)
    mes_comp = calcular_mes_anterior()
    historico = f"Folha INSS {mes_comp}"
    
    return {
        "Arquivo": arquivo,
        "Informe o Credor": limpar_cnpj("29.979.036/0001-40"),
        "Leitora Otica": "n",
        "Selecione com 'X'": "Patronal (GPS/DARF)",
        "Selecione a GUIA para Pagamento": "DARF",
        "Ano/Nr. Folha": "",
        "UO Contribuinte": uo_contribuinte,
        "Ordenador Despesa": "m1127166",
        "Nr Docto DARF": nr_doc_numeros,
        "Codigo de Barra": codigo_barras_numeros,
        "Valor Total do Documento": limpar_valor_monetario(valor_total),
        "Data Pagamento Prevista": limpar_data(data_pagamento),
        "Historico de Referencia": historico,
    }


def formatar_linha_servidor(registro: dict) -> dict:
    """
    Formata um registro para a aba "servidor".
    
    Args:
        registro: Dicionário com campos extraídos do PDF
        
    Returns:
        Dicionário com colunas formatadas para a aba servidor
    """
    arquivo = registro.get("arquivo", "") or ""
    cnpj = registro.get("cnpj", "") or ""
    numero_doc = registro.get("numero_documento", "") or ""
    linha_dig = registro.get("linha_digitavel", "") or ""
    valor_total = registro.get("valor_total_documento", "") or ""
    data_venc = registro.get("data_vencimento", "") or ""
    
    uo_contribuinte = get_uo_por_cnpj(cnpj) or ""
    nr_doc_numeros = extrair_apenas_numeros(numero_doc)
    codigo_barras_numeros = extrair_apenas_numeros(linha_dig)
    data_pagamento = calcular_data_menos_um_dia(data_venc)
    mes_comp = calcular_mes_anterior()
    historico = f"Folha INSS {mes_comp}"
    
    return {
        "Arquivo": arquivo,
        "Informe o Credor": limpar_cnpj("29.979.036/0001-40"),
        "Leitora Otica": "n",
        "Selecione com 'X'": "Consignacao (GPS/DARF)",
        "Selecione a GUIA para Pagamento": "DARF",
        "Mes/Ano de Competencia:": limpar_mes_ano(mes_comp),
        "UO Contribuinte": uo_contribuinte,
        "GMI FP": "",
        "Ordenador Despesa": "m1127166",
        "Nr Docto DARF": nr_doc_numeros,
        "Codigo de Barra": codigo_barras_numeros,
        "Valor Total do Documento": limpar_valor_monetario(valor_total),
        "Data Pagamento Prevista": limpar_data(data_pagamento),
        "Historico de Referencia": historico,
    }


def gerar_excel(
    registros_servidor: List[dict],
    registros_patronal: List[dict],
    todos_erros: List[dict],
    output_path: Path,
) -> Path:
    """
    Gera arquivo Excel com múltiplas abas a partir dos registros processados.
    
    Sempre cria as três abas (servidor, patronal-gilrat, erros), mesmo que vazias.
    
    Args:
        registros_servidor: Lista de registros formatados para aba servidor
        registros_patronal: Lista de registros formatados para aba patronal-gilrat
        todos_erros: Lista de erros formatados para aba erros
        output_path: Caminho onde o arquivo Excel será salvo
        
    Returns:
        Caminho do arquivo Excel gerado
    """
    with pd.ExcelWriter(output_path, engine="openpyxl") as writer:
        # Aba servidor (sempre criada, mesmo que vazia)
        if registros_servidor:
            df_servidor = pd.DataFrame(registros_servidor)
            df_servidor.to_excel(writer, sheet_name="servidor", index=False)
        else:
            # Cria aba vazia com cabeçalhos
            df_vazio_servidor = pd.DataFrame(columns=formatar_linha_servidor({}).keys())
            df_vazio_servidor.to_excel(writer, sheet_name="servidor", index=False)
        
        # Aba patronal-gilrat (sempre criada, mesmo que vazia)
        if registros_patronal:
            df_patronal = pd.DataFrame(registros_patronal)
            df_patronal.to_excel(writer, sheet_name="patronal-gilrat", index=False)
        else:
            # Cria aba vazia com cabeçalhos
            df_vazio_patronal = pd.DataFrame(columns=formatar_linha_patronal_gilrat({}).keys())
            df_vazio_patronal.to_excel(writer, sheet_name="patronal-gilrat", index=False)
        
        # Aba erros (sempre criada, mesmo que vazia)
        if todos_erros:
            erros_formatados = [formatar_linha_erro(erro) for erro in todos_erros]
            df_erros = pd.DataFrame(erros_formatados)
            df_erros.to_excel(writer, sheet_name="erros", index=False)
        else:
            # Cria aba vazia com cabeçalhos
            df_vazio_erros = pd.DataFrame(columns=["Arquivo", "Campo", "Tipo de Erro", "Mensagem", "Valor Extraído", "Severidade"])
            df_vazio_erros.to_excel(writer, sheet_name="erros", index=False)
    
    return output_path

