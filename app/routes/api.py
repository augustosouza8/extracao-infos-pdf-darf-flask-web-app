"""
Rotas API para gerenciamento de regras.

Contém as rotas REST para gerenciar códigos → abas e CNPJs → UO Contribuinte.
"""

from flask import Blueprint, request, jsonify

from app.database import (
    get_todos_codigos,
    get_todos_cnpjs,
    adicionar_codigo,
    remover_codigo,
    adicionar_cnpj,
    remover_cnpj,
)

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.route("/regras", methods=["GET"])
def get_regras():
    """
    Retorna todas as regras (códigos e CNPJs).
    
    Returns:
        JSON com códigos e CNPJs
    """
    try:
        codigos = get_todos_codigos()
        cnpjs = get_todos_cnpjs()
        return jsonify({
            "codigos": codigos,
            "cnpjs": cnpjs,
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/regras/codigo", methods=["POST"])
def adicionar_codigo_route():
    """
    Adiciona um novo código → aba.
    
    Body JSON:
        {
            "codigo": "1234",
            "aba": "servidor" ou "patronal-gilrat"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        codigo = data.get("codigo", "").strip()
        aba = data.get("aba", "").strip()
        
        if not codigo or not aba:
            return jsonify({"error": "Código e aba são obrigatórios"}), 400
        
        sucesso, mensagem = adicionar_codigo(codigo, aba)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/regras/codigo/<codigo>", methods=["DELETE"])
def remover_codigo_route(codigo):
    """
    Remove um código → aba.
    
    Args:
        codigo: Código a remover
    """
    try:
        sucesso, mensagem = remover_codigo(codigo)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/regras/cnpj", methods=["POST"])
def adicionar_cnpj_route():
    """
    Adiciona um novo CNPJ → UO Contribuinte.
    
    Body JSON:
        {
            "cnpj": "12.345.678/0001-90",
            "uo_contribuinte": "1071"
        }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Dados não fornecidos"}), 400
        
        cnpj = data.get("cnpj", "").strip()
        uo_contribuinte = data.get("uo_contribuinte", "").strip()
        
        if not cnpj or not uo_contribuinte:
            return jsonify({"error": "CNPJ e UO Contribuinte são obrigatórios"}), 400
        
        sucesso, mensagem = adicionar_cnpj(cnpj, uo_contribuinte)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@bp.route("/regras/cnpj/<path:cnpj>", methods=["DELETE"])
def remover_cnpj_route(cnpj):
    """
    Remove um CNPJ → UO Contribuinte.
    
    Args:
        cnpj: CNPJ a remover (formatado ou não)
    """
    try:
        sucesso, mensagem = remover_cnpj(cnpj)
        
        if sucesso:
            return jsonify({"success": True, "message": mensagem}), 200
        else:
            return jsonify({"success": False, "error": mensagem}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500

