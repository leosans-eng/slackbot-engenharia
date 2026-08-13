"""Mensagens de status editáveis no Slack (chat.postMessage + chat.update)."""

from __future__ import annotations

import logging
from typing import Callable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

logger = logging.getLogger(__name__)


class StatusMensagem:
    """Publica uma mensagem e atualiza o mesmo post conforme a etapa avança."""

    def __init__(self, client: WebClient, channel_id: str, titulo: str) -> None:
        self.client = client
        self.titulo = titulo.rstrip()
        self.channel_id = channel_id
        self.ts: str | None = None
        self._ultima = ""
        self._publicar(f"{self.titulo}\n_Preparando…_")

    def _publicar(self, texto: str) -> None:
        resposta = self.client.chat_postMessage(channel=self.channel_id, text=texto)
        self.channel_id = resposta.get("channel") or self.channel_id
        self.ts = resposta.get("ts")
        self._ultima = texto

    def etapa(self, texto: str) -> None:
        """Atualiza a linha de progresso abaixo do título."""
        corpo = f"{self.titulo}\n_{texto}_"
        self._atualizar(corpo)

    def finalizar(self, texto: str) -> None:
        """Substitui o status pela mensagem final (sucesso ou erro)."""
        self._atualizar(texto)

    def _atualizar(self, texto: str) -> None:
        if texto == self._ultima:
            return
        if not self.ts:
            self._publicar(texto)
            return
        try:
            self.client.chat_update(
                channel=self.channel_id,
                ts=self.ts,
                text=texto,
            )
            self._ultima = texto
        except SlackApiError as erro:
            logger.warning("Falha ao editar status Slack: %s", erro)
            # Fallback: não envia outra mensagem para não lotar notificações


ProgressCallback = Callable[[str], None]


def progress_noop(_texto: str) -> None:
    """Callback vazio para chamadas sem UI Slack."""
    return None
