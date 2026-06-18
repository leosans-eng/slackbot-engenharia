"""
Bot Slack — Socket Mode.

Antes de rodar, configure o app em api.slack.com (veja slack_bot/CONFIGURACAO_SLACK.md).
"""

from __future__ import annotations

import logging
import re

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from slack_bot.config import SlackConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MENSAGEM_AJUDA = (
    "Olá! Sou o BOT da Engenharia.\n\n"
    "• Em *canais*: mencione-me com `@bot olá`\n"
    "• Em *mensagem direta*: basta escrever `olá`\n"
    "• Em breve: envie um `.xlsx` e use `/i9formatar modelo=1`\n\n"
    "_Se não responder, confira `slack_bot/CONFIGURACAO_SLACK.md`_"
)


def _texto_parece_saudacao(texto: str) -> bool:
    texto = texto.lower().strip()
    return bool(re.search(r"\b(ol[aá]|oi|hello|hi|ajuda|help)\b", texto))


def criar_app() -> App:
    config = SlackConfig.from_env()
    config.validar()
    app = App(token=config.bot_token)

    @app.middleware
    def registrar_eventos(body, next):
        tipo = body.get("type")
        if tipo in ("events_api", "event_callback"):
            evento = body.get("event", {})
            logger.info("Evento recebido: %s", evento.get("type", "?"))
        elif tipo:
            logger.info("Payload recebido: %s", tipo)
        next()

    @app.error
    def tratar_erro(error, body, logger):
        logger.exception("Erro no handler Slack: %s", error)

    @app.event("app_mention")
    def mencao(event, say, client):
        logger.info("Handler app_mention — usuário=%s", event.get("user"))
        texto = event.get("text", "")
        # Remove a menção ao bot do texto (<@U123>)
        texto_limpo = re.sub(r"<@[^>]+>", "", texto).strip()
        if not texto_limpo or _texto_parece_saudacao(texto_limpo):
            say(MENSAGEM_AJUDA)
        else:
            say(
                f"Recebi: _{texto_limpo}_\n\n"
                "O comando `/i9formatar` com upload de planilha será implementado em seguida."
            )

    @app.event("message")
    def mensagem_direta(event, say, logger):
        if event.get("subtype") or event.get("bot_id"):
            return
        channel_type = event.get("channel_type")
        if channel_type and channel_type != "im":
            return

        logger.info("Handler message — usuário=%s canal=%s", event.get("user"), channel_type)
        texto = event.get("text", "").strip()
        if _texto_parece_saudacao(texto) or not texto:
            say(MENSAGEM_AJUDA)
        else:
            say(f"Recebi sua mensagem: _{texto}_")

    @app.command("/i9formatar")
    def comando_formatar(ack, command, say):
        ack()
        texto = (command.get("text") or "").strip()
        logger.info("Comando /i9formatar — texto=%r", texto)
        say(
            f"Comando recebido: `{texto or '(vazio)'}`\n"
            "Em breve: envie a planilha no canal e use `modelo=1`, `modelo=2` ou `modelo=3`."
        )

    return app


def main() -> None:
    config = SlackConfig.from_env()
    config.validar()
    logger.info("Iniciando bot (Socket Mode)...")
    logger.info(
        "Aguardando eventos. Teste com @menção no canal ou DM. "
        "Se nada aparecer aqui, veja slack_bot/CONFIGURACAO_SLACK.md"
    )
    app = criar_app()
    handler = SocketModeHandler(app, config.app_token)
    handler.start()


if __name__ == "__main__":
    main()
