"""Configuração do bot Slack."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class SlackConfig:
    bot_token: str
    app_token: str
    diretorio_temporario: str

    @classmethod
    def from_env(cls) -> SlackConfig:
        bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
        app_token = os.environ.get("SLACK_APP_TOKEN", "")
        diretorio_temporario = os.environ.get(
            "FORMATADOR_TEMP_DIR",
            os.path.join(os.getcwd(), "tmp", "slack"),
        )
        return cls(
            bot_token=bot_token,
            app_token=app_token,
            diretorio_temporario=diretorio_temporario,
        )

    def validar(self) -> None:
        if not self.bot_token:
            raise ValueError("SLACK_BOT_TOKEN não configurado.")
        if not self.app_token:
            raise ValueError("SLACK_APP_TOKEN não configurado (Socket Mode).")
