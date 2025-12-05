"""
Módulo de gerenciamento de configurações usando Flask-SQLAlchemy.

Suporta PostgreSQL (produção no Azure/Render) e SQLite (desenvolvimento local).

Gerencia as regras de mapeamento:
- Códigos → Abas (servidor/patronal-gilrat)
- CNPJ → UO Contribuinte

Nota: O banco de dados deve ser inicializado via migrations (Flask-Migrate)
e dados padrão populados via comando CLI (flask init-db).
"""

import re
from typing import Optional, Dict, List, Tuple

from sqlalchemy.exc import SQLAlchemyError

# Importa db e modelos - deve ser feito dentro de funções que usam contexto Flask
# para evitar problemas de import circular
def _get_db():
    """Retorna a instância db do Flask-SQLAlchemy."""
    from app import db
    return db

def _get_models():
    """Retorna os modelos."""
    from app.models import CodigoAba, CnpjUo
    return CodigoAba, CnpjUo

# Valores padrão para códigos → abas
CODIGOS_PADRAO = [
    ("1082", "servidor"),
    ("1099", "servidor"),
    ("1138", "patronal-gilrat"),
    ("1646", "patronal-gilrat"),
]

# Valores padrão para CNPJ → UO Contribuinte
CNPJS_PADRAO = [
    ("18.715.565/0001-10", "1071"),
    ("16.745.465/0001-01", "1081"),
    ("07.256.298/0001-44", "1101"),
    ("16.907.746/0001-13", "1191"),
    ("19.377.514/0001-99", "1221"),
    ("18.715.573/0001-67", "1231"),
    ("19.138.890/0001-20", "1271"),
    ("18.715.581/0001-03", "1301"),
    ("00.957.404/0001-78", "1371"),
    ("05.487.631/0001-09", "1451"),
    ("05.465.167/0001-41", "1481"),
    ("05.475.103/0001-21", "1491"),
    ("05.461.142/0001-70", "1501"),
    ("18.715.532/0001-70", "1511"),
    ("05.585.681/0001-10", "1521"),
    ("08.715.327/0001-51", "1541"),
    ("13.235.618/0001-82", "1631"),
    ("50.629.390/0001-31", "1711"),
    ("50.941.185/0001-07", "1721"),
]


# ======================================================================
# FUNÇÕES AUXILIARES
# ======================================================================

def normalizar_cnpj(cnpj: str) -> str:
    """Remove caracteres não numéricos do CNPJ."""
    return re.sub(r"\D", "", cnpj or "")


def formatar_cnpj(cnpj: str) -> str:
    """
    Formata CNPJ para o formato padrão: XX.XXX.XXX/XXXX-XX.
    
    Args:
        cnpj: CNPJ com ou sem formatação
        
    Returns:
        CNPJ formatado ou string vazia se inválido
    """
    if not cnpj:
        return ""
    
    # Remove formatação
    cnpj_limpo = normalizar_cnpj(cnpj)
    
    # Verifica se tem 14 dígitos
    if len(cnpj_limpo) != 14:
        return ""
    
    # Formata: XX.XXX.XXX/XXXX-XX
    return f"{cnpj_limpo[:2]}.{cnpj_limpo[2:5]}.{cnpj_limpo[5:8]}/{cnpj_limpo[8:12]}-{cnpj_limpo[12:14]}"


def validar_cnpj(cnpj: str) -> bool:
    """
    Valida CNPJ com dígitos verificadores.
    Algoritmo padrão da Receita.
    """
    digits = normalizar_cnpj(cnpj)
    if len(digits) != 14:
        return False

    # Descartar sequências repetidas (ex: 000000..., 111111..., etc.)
    if digits == digits[0] * 14:
        return False

    def calc_dv(digs, pesos):
        soma = sum(int(d) * p for d, p in zip(digs, pesos))
        r = soma % 11
        return "0" if r < 2 else str(11 - r)

    # Primeiro DV
    dv1 = calc_dv(digits[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    # Segundo DV
    dv2 = calc_dv(digits[:12] + dv1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])

    return digits[-2:] == dv1 + dv2


# ======================================================================
# FUNÇÃO PARA POPULAÇÃO DE DADOS PADRÃO
# ======================================================================

def init_db_data():
    """
    Popula o banco de dados com valores padrão se as tabelas estiverem vazias.
    
    Esta função deve ser chamada via comando CLI após as migrations.
    Flask-SQLAlchemy gerencia as sessões automaticamente.
    """
    db = _get_db()
    CodigoAba, CnpjUo = _get_models()
    
    try:
        # Verifica se codigo_aba está vazia
        count_codigos = db.session.query(CodigoAba).count()
        if count_codigos == 0:
            for codigo, aba in CODIGOS_PADRAO:
                db.session.add(CodigoAba(codigo=codigo, aba=aba))
            db.session.commit()
        
        # Verifica se cnpj_uo está vazia
        count_cnpjs = db.session.query(CnpjUo).count()
        if count_cnpjs == 0:
            for cnpj, uo in CNPJS_PADRAO:
                db.session.add(CnpjUo(cnpj=cnpj, uo_contribuinte=uo))
            db.session.commit()
    except Exception as e:
        db.session.rollback()
        raise Exception(f"Erro ao inicializar banco de dados: {e}")


# ======================================================================
# FUNÇÕES PARA CÓDIGOS → ABAS
# ======================================================================

def get_aba_por_codigo(codigo: str) -> Optional[str]:
    """
    Retorna a aba correspondente a um código.
    
    Args:
        codigo: Código de 4 dígitos
        
    Returns:
        "servidor", "patronal-gilrat" ou None se não encontrado
    """
    if not codigo:
        return None
    
    codigo_str = str(codigo).strip()
    db = _get_db()
    CodigoAba, _ = _get_models()
    
    # Flask-SQLAlchemy gerencia a sessão automaticamente
    registro = db.session.query(CodigoAba).filter(CodigoAba.codigo == codigo_str).first()
    return registro.aba if registro else None


def get_todos_codigos() -> List[Dict[str, str]]:
    """
    Retorna todos os códigos e suas abas correspondentes.
    
    Returns:
        Lista de dicionários com 'codigo' e 'aba'
    """
    db = _get_db()
    CodigoAba, _ = _get_models()
    
    registros = db.session.query(CodigoAba).order_by(CodigoAba.codigo).all()
    return [{"codigo": r.codigo, "aba": r.aba} for r in registros]


def adicionar_codigo(codigo: str, aba: str) -> Tuple[bool, str]:
    """
    Adiciona um novo código → aba.
    
    Args:
        codigo: Código de 4 dígitos
        aba: "servidor" ou "patronal-gilrat"
        
    Returns:
        Tupla (sucesso: bool, mensagem: str)
    """
    if not codigo:
        return False, "Código não pode ser vazio."
    
    codigo_str = str(codigo).strip()
    
    # Valida formato do código (4 dígitos)
    if not re.match(r"^\d{4}$", codigo_str):
        return False, "Código deve ter exatamente 4 dígitos."
    
    # Valida aba
    if aba not in ("servidor", "patronal-gilrat"):
        return False, "Aba deve ser 'servidor' ou 'patronal-gilrat'."
    
    db = _get_db()
    CodigoAba, _ = _get_models()
    
    try:
        # Verifica se já existe
        existe = db.session.query(CodigoAba).filter(CodigoAba.codigo == codigo_str).first()
        if existe:
            return False, f"Código {codigo_str} já existe."
        
        # Insere
        novo_codigo = CodigoAba(codigo=codigo_str, aba=aba)
        db.session.add(novo_codigo)
        db.session.commit()
        return True, f"Código {codigo_str} adicionado com sucesso."
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f"Erro ao adicionar código: {str(e)}"


def remover_codigo(codigo: str) -> Tuple[bool, str]:
    """
    Remove um código → aba.
    
    Args:
        codigo: Código a remover
        
    Returns:
        Tupla (sucesso: bool, mensagem: str)
    """
    if not codigo:
        return False, "Código não pode ser vazio."
    
    codigo_str = str(codigo).strip()
    db = _get_db()
    CodigoAba, _ = _get_models()
    
    try:
        registro = db.session.query(CodigoAba).filter(CodigoAba.codigo == codigo_str).first()
        if not registro:
            return False, f"Código {codigo_str} não encontrado."
        
        db.session.delete(registro)
        db.session.commit()
        return True, f"Código {codigo_str} removido com sucesso."
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f"Erro ao remover código: {str(e)}"


# ======================================================================
# FUNÇÕES PARA CNPJ → UO CONTRIBUINTE
# ======================================================================

def get_uo_por_cnpj(cnpj: str) -> Optional[str]:
    """
    Retorna a UO Contribuinte correspondente a um CNPJ.
    
    Args:
        cnpj: CNPJ formatado ou não
        
    Returns:
        Código UO ou None se não encontrado
    """
    if not cnpj:
        return None
    
    # Normaliza o CNPJ para o formato esperado
    cnpj_formatado = formatar_cnpj(cnpj)
    if not cnpj_formatado:
        return None
    
    db = _get_db()
    _, CnpjUo = _get_models()
    
    registro = db.session.query(CnpjUo).filter(CnpjUo.cnpj == cnpj_formatado).first()
    return registro.uo_contribuinte if registro else None


def get_todos_cnpjs() -> List[Dict[str, str]]:
    """
    Retorna todos os CNPJs e suas UOs correspondentes.
    
    Returns:
        Lista de dicionários com 'cnpj' e 'uo_contribuinte'
    """
    db = _get_db()
    _, CnpjUo = _get_models()
    
    registros = db.session.query(CnpjUo).order_by(CnpjUo.cnpj).all()
    return [{"cnpj": r.cnpj, "uo_contribuinte": r.uo_contribuinte} for r in registros]


def adicionar_cnpj(cnpj: str, uo_contribuinte: str) -> Tuple[bool, str]:
    """
    Adiciona um novo CNPJ → UO Contribuinte.
    
    Args:
        cnpj: CNPJ formatado ou não
        uo_contribuinte: Código UO Contribuinte
        
    Returns:
        Tupla (sucesso: bool, mensagem: str)
    """
    if not cnpj:
        return False, "CNPJ não pode ser vazio."
    
    if not uo_contribuinte:
        return False, "UO Contribuinte não pode ser vazio."
    
    # Valida CNPJ
    if not validar_cnpj(cnpj):
        return False, "CNPJ inválido (formato ou dígitos verificadores incorretos)."
    
    # Formata CNPJ
    cnpj_formatado = formatar_cnpj(cnpj)
    if not cnpj_formatado:
        return False, "CNPJ inválido (deve ter 14 dígitos)."
    
    # Valida UO (deve ser numérico)
    uo_str = str(uo_contribuinte).strip()
    if not re.match(r"^\d+$", uo_str):
        return False, "UO Contribuinte deve ser um código numérico."
    
    db = _get_db()
    _, CnpjUo = _get_models()
    
    try:
        # Verifica se já existe
        existe = db.session.query(CnpjUo).filter(CnpjUo.cnpj == cnpj_formatado).first()
        if existe:
            return False, f"CNPJ {cnpj_formatado} já existe."
        
        # Insere
        novo_cnpj = CnpjUo(cnpj=cnpj_formatado, uo_contribuinte=uo_str)
        db.session.add(novo_cnpj)
        db.session.commit()
        return True, f"CNPJ {cnpj_formatado} adicionado com sucesso."
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f"Erro ao adicionar CNPJ: {str(e)}"


def remover_cnpj(cnpj: str) -> Tuple[bool, str]:
    """
    Remove um CNPJ → UO Contribuinte.
    
    Args:
        cnpj: CNPJ a remover (formatado ou não)
        
    Returns:
        Tupla (sucesso: bool, mensagem: str)
    """
    if not cnpj:
        return False, "CNPJ não pode ser vazio."
    
    # Formata CNPJ
    cnpj_formatado = formatar_cnpj(cnpj)
    if not cnpj_formatado:
        return False, "CNPJ inválido (deve ter 14 dígitos)."
    
    db = _get_db()
    _, CnpjUo = _get_models()
    
    try:
        registro = db.session.query(CnpjUo).filter(CnpjUo.cnpj == cnpj_formatado).first()
        if not registro:
            return False, f"CNPJ {cnpj_formatado} não encontrado."
        
        db.session.delete(registro)
        db.session.commit()
        return True, f"CNPJ {cnpj_formatado} removido com sucesso."
    except SQLAlchemyError as e:
        db.session.rollback()
        return False, f"Erro ao remover CNPJ: {str(e)}"
