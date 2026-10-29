"""Botões do Slack para escolha de imóvel, modelo SINAPI e revisão."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field

from slack_sdk import WebClient

from bot.status_msg import chamar_slack_com_retry

logger = logging.getLogger(__name__)

ACAO_IMOVEL = "escolher_imovel"
ACAO_REVISAO_FINALIZAR = "revisao_finalizar"
ACAO_REVISAO_CANCELAR = "revisao_cancelar"
ACAO_MODELO_PREFIXO = "formatar_modelo_"

LIMITE_BOTOES_IMOVEL = 40
LIMITE_VALOR = 1900
LIMITE_TEXTO_BLOCO = 2900

_em_andamento: set[str] = set()
_lock = threading.Lock()


@dataclass(frozen=True)
class RespostaComBotoes:
    """Mensagem com botões. `alternativa` é o texto se o Slack recusar os blocos."""

    texto: str
    blocks: list[dict] = field(default_factory=list)
    alternativa: str = ""


def ocupar_mensagem(ts: str) -> bool:
    """Evita dois cliques no mesmo recado dispararem o trabalho duas vezes."""
    if not ts:
        return True
    with _lock:
        if ts in _em_andamento:
            return False
        _em_andamento.add(ts)
        return True


def ler_valor_acao(action: dict) -> dict:
    bruto = (action or {}).get("value") or ""
    try:
        dados = json.loads(bruto)
    except (TypeError, json.JSONDecodeError):
        return {}
    return dados if isinstance(dados, dict) else {}


def montar_escolha_imovel(
    comando: str,
    nome: str,
    rotulos: list[str],
    user_id: str,
    *,
    alternativa: str,
) -> RespostaComBotoes:
    """Um botão por imóvel. O valor repete a busca com opcao=N."""
    total = len(rotulos)
    visiveis = rotulos[:LIMITE_BOTOES_IMOVEL]
    intro = (
        f"Encontrei *{total}* imóveis para \"{_escapar(nome)}\".\n"
        "Escolha um:"
    )
    blocks: list[dict] = [_secao(intro)]
    for indice, rotulo in enumerate(visiveis, start=1):
        preview = " ".join(rotulo.split())
        if len(preview) > 180:
            preview = preview[:177] + "..."
        valor = _valor({"c": comando, "n": nome, "i": indice, "u": user_id})
        blocks.append(
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*[{indice}]* {_escapar(preview)}",
                },
                "accessory": _botao(str(indice), ACAO_IMOVEL, valor),
            }
        )
    if total > len(visiveis):
        blocks.append(
            _contexto(
                f"Mostrando os {len(visiveis)} primeiros. "
                f"Para os demais: `/{comando} {_codigo(nome)} opcao=N`."
            )
        )
    else:
        blocks.append(
            _contexto(
                f"Se o botão não responder: `/{comando} {_codigo(nome)} opcao=N`."
            )
        )
    return RespostaComBotoes(
        texto=f"Encontrei {total} imóveis para {nome}. Escolha um.",
        blocks=blocks,
        alternativa=alternativa,
    )


def blocos_modelos(nome_arquivo: str, user_id: str) -> RespostaComBotoes:
    texto = (
        f"Planilha recebida: *{_escapar(nome_arquivo)}*\n"
        "Escolha o modelo:"
    )
    botoes = [
        ("Atualização", 1),
        ("Perito", 2),
        ("Parecer Inicial", 3),
    ]
    return RespostaComBotoes(
        texto=f"Planilha recebida: {nome_arquivo}. Escolha o modelo.",
        blocks=[
            _secao(texto),
            {
                "type": "actions",
                "elements": [
                    _botao(
                        rotulo,
                        f"{ACAO_MODELO_PREFIXO}{modelo}",
                        _valor({"m": modelo, "u": user_id}),
                    )
                    for rotulo, modelo in botoes
                ],
            },
            _contexto("Se o botão não responder: `/i9formatar 1`, `2` ou `3`."),
        ],
        alternativa=(
            f"Planilha recebida: *{nome_arquivo}*\n"
            "Rode `/i9formatar 1` (Atualização), `2` (Perito) ou `3` (Parecer Inicial)."
        ),
    )


def blocos_revisao(user_id: str) -> RespostaComBotoes:
    return RespostaComBotoes(
        texto="Finalizar ou cancelar a prévia da revisão.",
        blocks=[
            _secao("Finalizar os pareceres desta prévia ou descartar."),
            {
                "type": "actions",
                "elements": [
                    _botao(
                        "Finalizar",
                        ACAO_REVISAO_FINALIZAR,
                        _valor({"u": user_id}),
                        style="primary",
                    ),
                    _botao(
                        "Cancelar",
                        ACAO_REVISAO_CANCELAR,
                        _valor({"u": user_id}),
                        style="danger",
                    ),
                ],
            },
            _contexto("Se o botão não responder, escreva *sim* ou *não* neste canal."),
        ],
    )


def postar_botoes(
    client: WebClient,
    channel_id: str,
    resposta: RespostaComBotoes,
):
    return chamar_slack_com_retry(
        lambda: client.chat_postMessage(
            channel=channel_id,
            text=resposta.texto,
            blocks=resposta.blocks,
        ),
        "chat.postMessage (botões)",
    )


def substituir_mensagem_botoes(
    client: WebClient,
    channel_id: str,
    ts: str,
    texto: str,
) -> None:
    """Troca os botões por uma frase, para o clique não disparar de novo."""
    if not channel_id or not ts:
        return
    visivel = texto if len(texto) <= LIMITE_TEXTO_BLOCO else texto[: LIMITE_TEXTO_BLOCO - 1] + "…"
    chamar_slack_com_retry(
        lambda: client.chat_update(
            channel=channel_id,
            ts=ts,
            text=visivel,
            blocks=[_secao(visivel)],
        ),
        "chat.update (botões)",
    )


def _botao(
    rotulo: str,
    action_id: str,
    valor: str,
    *,
    style: str | None = None,
) -> dict:
    elemento = {
        "type": "button",
        "text": {"type": "plain_text", "text": rotulo[:75], "emoji": False},
        "action_id": action_id,
        "value": valor,
    }
    if style:
        elemento["style"] = style
    return elemento


def _secao(texto: str) -> dict:
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": texto[:LIMITE_TEXTO_BLOCO]},
    }


def _contexto(texto: str) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": texto[:LIMITE_TEXTO_BLOCO]}],
    }


def _valor(dados: dict) -> str:
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    if len(texto) <= LIMITE_VALOR:
        return texto
    if "n" in dados:
        dados = dict(dados)
        dados["n"] = str(dados["n"])[:80]
        texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    return texto


def _escapar(texto: str) -> str:
    return (
        (texto or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _codigo(texto: str) -> str:
    return (texto or "").replace("`", "'")
