"""Resolução de nomes de usuário do Slack para logs."""

from __future__ import annotations

import logging

from slack_sdk import WebClient

logger = logging.getLogger(__name__)

_nomes_cache: dict[str, str] = {}


def nome_usuario(client: WebClient, user_id: str) -> str:
    if not user_id:
        return "?"
    if user_id in _nomes_cache:
        return _nomes_cache[user_id]

    try:
        resposta = client.users_info(user=user_id)
        usuario = resposta.get("user", {})
        perfil = usuario.get("profile", {})
        nome = (
            usuario.get("real_name")
            or perfil.get("display_name")
            or perfil.get("real_name")
            or usuario.get("name")
            or user_id
        )
        _nomes_cache[user_id] = nome
        return nome
    except Exception as erro:
        logger.debug("Não foi possível obter nome de %s: %s", user_id, erro)
        return user_id


def rotulo_usuario(client: WebClient, user_id: str) -> str:
    nome = nome_usuario(client, user_id)
    if nome == user_id:
        return f"usuário={user_id}"
    return f"usuário={nome} ({user_id})"


MENSAGEM_SEM_PERMISSAO_REVISAO = (
    "Você não tem permissão para usar este comando. Contate um Administrador."
)


def usuario_pode_revisao(user_id: str) -> bool:
    from ferramentas.idebras.config import REVISAO_USUARIOS

    return bool(user_id) and user_id in REVISAO_USUARIOS
