"""
Bot Slack — esqueleto Socket Mode.

Configure as variáveis em .env (veja .env.example) e implemente os handlers
em handlers.py conforme o fluxo desejado (slash command, atalho de mensagem, etc.).
"""

from __future__ import annotations

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from slack_bot.config import SlackConfig


def criar_app() -> App:
    config = SlackConfig.from_env()
    config.validar()
    app = App(token=config.bot_token)

    @app.event("app_mention")
    def mencao(event, say):
        say(
            "Olá! Envie uma planilha SINAPI (.xlsx) e use "
            "`/formatar modelo=1` para formatar. "
            "(Handler completo ainda não implementado.)"
        )

    # TODO: slash command /formatar, download de arquivo compartilhado,
    # processamento assíncrono com slack_bot.handlers.processar_upload

    return app


def main() -> None:
    config = SlackConfig.from_env()
    config.validar()
    app = criar_app()
    handler = SocketModeHandler(app, config.app_token)
    handler.start()


if __name__ == "__main__":
    main()
