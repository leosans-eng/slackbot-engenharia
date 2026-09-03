"""Mensagens de status editáveis no Slack (chat.postMessage + chat.update)."""

from __future__ import annotations

import logging
import time
from typing import Callable

from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

from bot.files import eh_erro_rede_transiente

logger = logging.getLogger(__name__)

# chat.update recusa texto longo (msg_too_long). chat.postMessage aceita mais.
LIMITE_CHAT_UPDATE = 3500
TENTATIVAS_REDE = 3


def partir_texto_slack(texto: str, limite: int = LIMITE_CHAT_UPDATE) -> list[str]:
    texto = (texto or "").rstrip()
    if not texto:
        return [""]
    partes: list[str] = []
    resto = texto
    while resto:
        if len(resto) <= limite:
            partes.append(resto)
            break
        corte = resto.rfind("\n", 0, limite)
        if corte < limite // 3:
            corte = limite
        partes.append(resto[:corte].rstrip())
        resto = resto[corte:].lstrip("\n")
    return partes or [""]


class StatusMensagem:
    """Publica uma mensagem e atualiza o mesmo post conforme a etapa avança."""

    def __init__(self, client: WebClient, channel_id: str, titulo: str) -> None:
        self.client = client
        self.titulo = titulo.rstrip()
        self.channel_id = channel_id
        self.ts: str | None = None
        self._ultima = ""
        self._publicar(f"{self.titulo}\n_Preparando…_")

    def _com_retry(self, operacao, rotulo: str):
        ultimo: BaseException | None = None
        for tentativa in range(1, TENTATIVAS_REDE + 1):
            try:
                return operacao()
            except SlackApiError as erro:
                ultimo = erro
                codigo = ""
                try:
                    codigo = (erro.response or {}).get("error") or ""
                except Exception:
                    pass
                if codigo == "msg_too_long" or not eh_erro_rede_transiente(erro):
                    raise
                if tentativa >= TENTATIVAS_REDE:
                    raise
                espera = 2**tentativa
                logger.warning(
                    "%s falhou (%s). Tentativa %s/%s em %ss.",
                    rotulo,
                    erro,
                    tentativa,
                    TENTATIVAS_REDE,
                    espera,
                )
                time.sleep(espera)
            except Exception as erro:
                ultimo = erro
                if tentativa >= TENTATIVAS_REDE or not eh_erro_rede_transiente(erro):
                    raise
                espera = 2**tentativa
                logger.warning(
                    "%s falhou (%s). Tentativa %s/%s em %ss.",
                    rotulo,
                    erro,
                    tentativa,
                    TENTATIVAS_REDE,
                    espera,
                )
                time.sleep(espera)
        raise ultimo or RuntimeError(f"{rotulo} falhou")

    def _publicar(self, texto: str) -> None:
        resposta = self._com_retry(
            lambda: self.client.chat_postMessage(channel=self.channel_id, text=texto),
            "chat.postMessage",
        )
        self.channel_id = resposta.get("channel") or self.channel_id
        self.ts = resposta.get("ts")
        self._ultima = texto

    def etapa(self, texto: str) -> None:
        """Atualiza a linha de progresso abaixo do título."""
        corpo = f"{self.titulo}\n_{texto}_"
        self._atualizar(corpo)

    def finalizar(self, texto: str) -> None:
        """Substitui o status pela mensagem final (sucesso ou erro)."""
        partes = partir_texto_slack(texto)
        if not self._atualizar(partes[0]):
            self._encerrar_status_travado()
            self._postar_continuacao(partes[0])
        for parte in partes[1:]:
            self._postar_continuacao(parte)

    def _encerrar_status_travado(self) -> None:
        if not self.ts:
            return
        try:
            self.client.chat_update(
                channel=self.channel_id,
                ts=self.ts,
                text="✅ Concluído. Detalhes nas mensagens seguintes.",
            )
        except Exception as erro:
            logger.warning("Falha ao encerrar status Slack: %s", erro)

    def _atualizar(self, texto: str) -> bool:
        if texto == self._ultima:
            return True
        if not self.ts:
            try:
                self._publicar(texto)
                return True
            except Exception as erro:
                logger.warning("Falha ao publicar status Slack: %s", erro)
                return False
        try:
            self._com_retry(
                lambda: self.client.chat_update(
                    channel=self.channel_id,
                    ts=self.ts,
                    text=texto,
                ),
                "chat.update",
            )
            self._ultima = texto
            return True
        except SlackApiError as erro:
            logger.warning("Falha ao editar status Slack: %s", erro)
            return False
        except Exception as erro:
            logger.warning("Falha ao editar status Slack: %s", erro)
            return False

    def _postar_continuacao(self, texto: str) -> None:
        if not texto:
            return
        try:
            self._com_retry(
                lambda: self.client.chat_postMessage(
                    channel=self.channel_id,
                    text=texto,
                ),
                "chat.postMessage (continuação)",
            )
        except Exception as erro:
            logger.warning("Falha ao enviar continuação Slack: %s", erro)


ProgressCallback = Callable[[str], None]


def progress_noop(_texto: str) -> None:
    """Callback vazio para chamadas sem UI Slack."""
    return None
