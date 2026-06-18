"""
Bot Slack — Socket Mode.
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

from slack_bot.handlers import executar_comando_formatar, registrar_arquivos_da_mensagem


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

logger = logging.getLogger(__name__)

MENSAGEM_AJUDA = (
    "Olá! Sou o *BOT da Engenharia*. Atualmente, estou programado apenas para formatar planilhas SINAPI.\n\n"

    "*Como formatar:*\n"
    "1. Envie a planilha `.xlsx` neste canal ou DM\n"
    "2. Rode o comando:\n"
    "   `/i9formatar modelo=1` — Atualização (+ Word)\n"
    "   `/i9formatar modelo=2` — Enviar ao Perito (Planilha com fórmulas)\n"
    "   `/i9formatar modelo=3` — Parecer Inicial (+ Word)\n\n"

    "Colocar apenas o número também funciona. Exemplo: `/i9formatar 2` irá gerar o Modelo 2."
)


def _texto_parece_saudacao(texto: str) -> bool:

    texto = texto.lower().strip()
    return bool(re.search(r"\b(ol[aá]|oi|hello|hi|ajuda|help)\b", texto))


def _tratar_arquivos_na_mensagem(event, say=None) -> bool:

    """Registra planilhas anexadas. Retorna True se havia .xlsx."""

    arquivos = event.get("files") or []

    if not arquivos:
        return False

    user_id = event.get("user")

    channel_id = event.get("channel")

    if not user_id or not channel_id:
        return False

    pendente = registrar_arquivos_da_mensagem(user_id, channel_id, arquivos)

    if pendente and say:

        say(
            f"📎 Planilha recebida: *{pendente.nome}*\n"
            f"Agora rode `/i9formatar modelo=1` (ou `2`, `3`)."
        )

    return pendente is not None


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


    @app.event("message")

    def ao_receber_mensagem(event, say, logger):

        if event.get("bot_id"):
            return

        subtype = event.get("subtype")

        if subtype and subtype not in ("file_share", "file_comment"):
            return

        if _tratar_arquivos_na_mensagem(event, say=say):
            return

        channel_type = event.get("channel_type")

        if channel_type and channel_type != "im":
            return

        logger.info("Handler message — usuário=%s", event.get("user"))

        texto = event.get("text", "").strip()

        if _texto_parece_saudacao(texto) or not texto:

            say(MENSAGEM_AJUDA)


    @app.event("app_mention")

    def mencao(event, say):

        logger.info("Handler app_mention — usuário=%s", event.get("user"))

        if _tratar_arquivos_na_mensagem(event, say=say):
            return

        texto = event.get("text", "")

        texto_limpo = re.sub(r"<@[^>]+>", "", texto).strip()

        if not texto_limpo or _texto_parece_saudacao(texto_limpo):
            say(MENSAGEM_AJUDA)

        else:
            say(
                f"Recebi: _{texto_limpo}_\n\n"

                "Para formatar, envie um `.xlsx` e use `/i9formatar modelo=1`."
            )


    @app.command("/i9formatar")

    def comando_formatar(ack, command, say, client, logger):

        ack()

        user_id = command.get("user_id", "")

        channel_id = command.get("channel_id", "")

        texto = (command.get("text") or "").strip()

        logger.info("Comando /i9formatar — usuário=%s texto=%r", user_id, texto)

        say("⏳ Processando planilha…")

        try:

            mensagem = executar_comando_formatar(
                client,
                config,
                channel_id,
                user_id,
                texto,
            )

            say(mensagem)

        except ValueError as erro:
            say(f"❌ {erro}")

        except Exception as erro:
            logger.exception("Falha ao formatar planilha")
            say(f"❌ Erro ao formatar: {erro}")

    return app


def main() -> None:

    config = SlackConfig.from_env()

    config.validar()

    logger.info("Iniciando bot (Socket Mode)...")

    logger.info(
        "Aguardando eventos. Envie um .xlsx e use /i9formatar modelo=1. "
        "Configuração: slack_bot/CONFIGURACAO_SLACK.md"
    )

    app = criar_app()

    handler = SocketModeHandler(app, config.app_token)

    handler.start()


if __name__ == "__main__":

    main()