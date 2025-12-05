"""
Modelos SQLAlchemy para o banco de dados.

Define os modelos CodigoAba e CnpjUo usando Flask-SQLAlchemy.
"""

from sqlalchemy import CheckConstraint
from app import db


class CodigoAba(db.Model):
    """Modelo para tabela de códigos → abas."""
    __tablename__ = "codigo_aba"
    
    codigo = db.Column(db.String, primary_key=True)
    aba = db.Column(db.String, nullable=False)
    
    __table_args__ = (
        CheckConstraint("aba IN ('servidor', 'patronal-gilrat')", name="check_aba"),
    )


class CnpjUo(db.Model):
    """Modelo para tabela de CNPJ → UO Contribuinte."""
    __tablename__ = "cnpj_uo"
    
    cnpj = db.Column(db.String, primary_key=True)
    uo_contribuinte = db.Column(db.String, nullable=False)

