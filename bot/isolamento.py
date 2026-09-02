"""Roda tarefas da pasta de rede / Idebras em processo separado, com timeout.

No Windows, um `rglob` em drive mapeado desconectado (B:\\) pode travar o
processo inteiro. Isolar em outro processo permite encerrar a tarefa travada
sem derrubar o Socket Mode do Slack.
"""

from __future__ import annotations

import logging
import multiprocessing
from queue import Empty
from typing import Any, Callable

logger = logging.getLogger(__name__)

TIMEOUT_DOWNLOAD_HORARIO = 12 * 60
TIMEOUT_COMANDO_REVISAO = 20 * 60


def _encerrar(proc: multiprocessing.Process) -> None:
    if not proc.is_alive():
        return
    proc.terminate()
    proc.join(15)
    if proc.is_alive():
        proc.kill()
        proc.join(5)


def rodar_processo(
    target: Callable,
    args: tuple,
    *,
    timeout: float,
    nome: str,
) -> None:
    logger.info("Processo isolado %s (timeout %ss)", nome, int(timeout))
    proc = multiprocessing.Process(target=target, args=args, name=nome, daemon=True)
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        logger.error("%s travado após %ss — encerrando processo.", nome, int(timeout))
        _encerrar(proc)
        raise TimeoutError(
            f"{nome} excedeu {int(timeout)} segundos "
            "(pasta de rede ou Idebras sem resposta)."
        )
    if proc.exitcode not in (0, None):
        raise RuntimeError(f"{nome} encerrou com código {proc.exitcode}.")


def rodar_processo_resultado(
    target: Callable,
    args: tuple,
    *,
    timeout: float,
    nome: str,
) -> Any:
    fila: multiprocessing.Queue = multiprocessing.Queue()
    logger.info("Processo isolado %s (timeout %ss)", nome, int(timeout))
    proc = multiprocessing.Process(
        target=target,
        args=(fila, *args),
        name=nome,
        daemon=True,
    )
    proc.start()
    proc.join(timeout)
    if proc.is_alive():
        logger.error("%s travado após %ss — encerrando processo.", nome, int(timeout))
        _encerrar(proc)
        raise TimeoutError(
            f"{nome} excedeu {int(timeout)} segundos "
            "(pasta de rede ou Idebras sem resposta)."
        )
    try:
        status, payload = fila.get_nowait()
    except Empty as exc:
        codigo = proc.exitcode
        if codigo not in (0, None):
            raise RuntimeError(f"{nome} encerrou com código {codigo}.") from exc
        raise RuntimeError(f"{nome} terminou sem devolver resultado.") from exc
    if status != "ok":
        raise RuntimeError(str(payload))
    return payload


def alvo_download_revisao(token: str, destinos: list[str]) -> None:
    from slack_sdk import WebClient

    from bot.handlers import executar_download_revisao_agendado

    client = WebClient(token=token, timeout=30)
    executar_download_revisao_agendado(client, destinos)


def alvo_finalizar_revisao(fila: multiprocessing.Queue, modo: str) -> None:
    try:
        from ferramentas.idebras.revisao_parecer import finalizar_revisoes_parecer

        resultado = finalizar_revisoes_parecer(modo=modo)
        fila.put(
            (
                "ok",
                {
                    "mensagem": resultado.mensagem_slack(),
                    "a_finalizar": len(resultado.a_finalizar),
                },
            )
        )
    except Exception as exc:
        fila.put(("err", f"{type(exc).__name__}: {exc}"))
