"""Job isolado: download horário da revisão (não importa bot.app)."""

from __future__ import annotations

import json
import logging
import os
import sys

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def _codigo_saida(exc: BaseException) -> int:
    from bot.isolamento import CODIGO_IDEBRAS_500, erro_idebras_instavel

    return CODIGO_IDEBRAS_500 if erro_idebras_instavel(exc) else 1


def main() -> None:
    from slack_sdk import WebClient

    from bot.handlers import executar_download_revisao_agendado

    token = os.environ.get("SLACK_BOT_TOKEN") or ""
    destinos = json.loads(os.environ.get("REVISAO_JOB_DESTINOS") or "[]")
    if not token:
        raise RuntimeError("SLACK_BOT_TOKEN ausente.")
    if not isinstance(destinos, list):
        raise RuntimeError("REVISAO_JOB_DESTINOS inválido.")
    client = WebClient(token=token, timeout=30)
    executar_download_revisao_agendado(client, destinos)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        logger.exception("Falha no download horário da revisão")
        sys.exit(_codigo_saida(exc))
