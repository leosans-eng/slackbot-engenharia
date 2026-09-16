"""Job isolado: /revisao preview, download ou finalizar (não importa bot.app)."""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

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


def _gravar(caminho: str, payload: dict) -> None:
    Path(caminho).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )


def main() -> int:
    modo = os.environ.get("REVISAO_JOB_MODO") or ""
    saida = os.environ.get("REVISAO_JOB_SAIDA") or ""
    if not modo or not saida:
        raise RuntimeError("REVISAO_JOB_MODO / REVISAO_JOB_SAIDA ausentes.")

    from ferramentas.idebras.revisao_parecer import finalizar_revisoes_parecer

    try:
        resultado = finalizar_revisoes_parecer(modo=modo)
        _gravar(
            saida,
            {
                "status": "ok",
                "resultado": {
                    "mensagem": resultado.mensagem_slack(),
                    "a_finalizar": len(resultado.a_finalizar),
                },
            },
        )
        return 0
    except Exception as exc:
        logger.exception("Falha no job de revisão (%s)", modo)
        _gravar(
            saida,
            {"status": "err", "erro": f"{type(exc).__name__}: {exc}"},
        )
        return _codigo_saida(exc)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        logger.exception("Falha no job de revisão")
        saida = os.environ.get("REVISAO_JOB_SAIDA") or ""
        if saida:
            try:
                _gravar(
                    saida,
                    {"status": "err", "erro": f"{type(exc).__name__}: {exc}"},
                )
            except OSError:
                pass
        sys.exit(_codigo_saida(exc))
