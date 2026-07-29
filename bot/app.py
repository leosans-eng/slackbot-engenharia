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

from bot.config import SlackConfig
from bot.handlers import (
    executar_comando_fotos,
    executar_comando_formatar,
    executar_comando_pericias,
    registrar_arquivos_da_mensagem,
)
from bot.usuarios import rotulo_usuario

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

MENSAGEM_AJUDA = (
    "Olá! Sou o *BOT da Engenharia*. Comandos disponíveis:\n\n"
    "*Formatar planilha SINAPI (i9):*\n"
    "1. Envie a planilha `.xlsx` neste canal ou DM\n"
    "2. Rode o comando:\n"
    "   `/i9formatar modelo=1` — Atualização (+ Word)\n"
    "   `/i9formatar modelo=2` — Enviar ao Perito (Planilha com fórmulas)\n"
    "   `/i9formatar modelo=3` — Parecer Inicial (+ Word)\n\n"
    "*Fotos do imóvel (Idebras):*\n"
    "   `/fotos Nome do Proprietário`\n"
    "   `/fotos Nome do Proprietário index=2` — se houver vários imóveis\n\n"
    "*Perícias finalizadas (Idebras):*\n"
    "   `/pericias` — data de hoje\n"
    "   `/pericias ontem`\n"
    "   `/pericias 28/07/2026` — data específica"
)

MENSAGEM_NAO_PROGRAMADA = (
    "Recebi sua mensagem: _{texto}_, mas não fui programado para responder a isso ainda. Diga *oi* para receber os comandos disponíveis."
)


def _texto_parece_saudacao(texto: str) -> bool:
    texto = texto.lower().strip()
    return bool(re.search(r"\b(ol[aá]|oi|hello|hi|ajuda|help|teste|testando|eai|eae|comando|comandos)\b", texto))


def _resposta_secreta(texto: str) -> str | None:
    chave = texto.lower().strip()
    if chave == "ping":
        return "Pong!"
    if chave == "cpj":
        return "Adilsooooon, os meninos já aprenderam o CPJ?"
    return None


def _log_interacao(client, user_id: str, texto: str, origem: str) -> None:
    logger.info(
        "%s — %s — mensagem=%r",
        origem,
        rotulo_usuario(client, user_id),
        texto,
    )


def _tratar_arquivos_na_mensagem(event, client, say=None) -> bool:
    """Registra planilhas anexadas. Retorna True se havia .xlsx."""
    arquivos = event.get("files") or []
    if not arquivos:
        return False

    user_id = event.get("user")
    channel_id = event.get("channel")
    if not user_id or not channel_id:
        return False

    nomes = [a.get("name", "?") for a in arquivos]
    _log_interacao(client, user_id, f"[arquivos: {', '.join(nomes)}]", "message (anexo)")

    pendente = registrar_arquivos_da_mensagem(user_id, channel_id, arquivos, client=client)
    if pendente and say:
        say(
            f"📎 Planilha recebida: *{pendente.nome}*\n"
            f"Agora rode `/i9formatar 1` para Atualização (+ Word), `2` para Enviar ao Perito ou `3` para Parecer Inicial (+ Word)."
        )
    return pendente is not None


def _responder_texto_dm(event, say, client) -> None:
    user_id = event.get("user", "")
    texto = (event.get("text") or "").strip()
    _log_interacao(client, user_id, texto, "message")

    resposta_secreta = _resposta_secreta(texto)
    if resposta_secreta:
        say(resposta_secreta)
        return

    if _texto_parece_saudacao(texto) or not texto:
        say(MENSAGEM_AJUDA)
        return

    say(MENSAGEM_NAO_PROGRAMADA.format(texto=texto))


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
    def ao_receber_mensagem(event, say, client):
        if event.get("bot_id"):
            return

        subtype = event.get("subtype")
        if subtype and subtype not in ("file_share", "file_comment"):
            return

        if _tratar_arquivos_na_mensagem(event, client, say=say):
            return

        channel_type = event.get("channel_type")
        if channel_type and channel_type != "im":
            return

        _responder_texto_dm(event, say, client)

    @app.event("app_mention")
    def mencao(event, say, client):
        user_id = event.get("user", "")
        texto = event.get("text", "")
        texto_limpo = re.sub(r"<@[^>]+>", "", texto).strip()
        _log_interacao(client, user_id, texto_limpo, "app_mention")

        if _tratar_arquivos_na_mensagem(event, client, say=say):
            return

        resposta_secreta = _resposta_secreta(texto_limpo)
        if resposta_secreta:
            say(resposta_secreta)
            return

        if not texto_limpo or _texto_parece_saudacao(texto_limpo):
            say(MENSAGEM_AJUDA)
        else:
            say(
                f"Recebi: _{texto_limpo}_\n\n"
                "Diga *oi* para ver os comandos (`/i9formatar`, `/fotos`, `/pericias`)."
            )

    @app.command("/i9formatar")
    def comando_formatar(ack, command, say, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /i9formatar")

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

    @app.command("/fotos")
    def comando_fotos(ack, command, say, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /fotos")

        say("⏳ Buscando fotos no Idebras…")

        try:
            mensagem = executar_comando_fotos(client, config, channel_id, texto)
            say(mensagem)
        except ValueError as erro:
            say(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao baixar fotos")
            say(f"❌ Erro ao baixar fotos: {erro}")

    @app.command("/pericias")
    def comando_pericias(ack, command, say, client, logger):
        ack()
        user_id = command.get("user_id", "")
        channel_id = command.get("channel_id", "")
        texto = (command.get("text") or "").strip()
        _log_interacao(client, user_id, texto, "comando /pericias")

        say("⏳ Gerando planilha de perícias finalizadas…")

        try:
            mensagem = executar_comando_pericias(client, config, channel_id, texto)
            say(mensagem)
        except ValueError as erro:
            say(f"❌ {erro}")
        except Exception as erro:
            logger.exception("Falha ao gerar perícias")
            say(f"❌ Erro ao gerar perícias: {erro}")

    return app


def main() -> None:
    config = SlackConfig.from_env()
    config.validar()
    logger.info("Iniciando bot (Socket Mode)...")
    logger.info(
        "Aguardando eventos. Comandos: /i9formatar, /fotos, /pericias. "
        "Configuração: bot/CONFIGURACAO.md"
    )
    app = criar_app()
    handler = SocketModeHandler(app, config.app_token)
    handler.start()


if __name__ == "__main__":
    main()
