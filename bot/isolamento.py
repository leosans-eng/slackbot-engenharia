"""Roda tarefas da pasta de rede / Idebras em processo separado, com timeout.

No Windows, `multiprocessing.Process.start()` reimporta o pacote `bot` e pode
travar o handshake (o job horário chega a ficar minutos em “Executando download”
sem chegar a “Processo isolado”). `subprocess.Popen` de `python -m bot.job_*`
evita isso: o timeout vale desde o spawn e o Socket Mode continua no Slack.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

TIMEOUT_DOWNLOAD_HORARIO = 12 * 60
TIMEOUT_COMANDO_REVISAO = 20 * 60
CODIGO_IDEBRAS_500 = 2
ROOT_DIR = Path(__file__).resolve().parent.parent


def _flags_criacao() -> int:
    if sys.platform == "win32":
        # CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW
        return subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000
    return 0


def _encerrar(proc: subprocess.Popen) -> None:
    if proc.poll() is not None:
        return
    if sys.platform == "win32" and proc.pid:
        # Mata a árvore inteira (python -m + filhos), não só o processo raiz.
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=30,
                check=False,
            )
        except Exception:
            pass
        if proc.poll() is not None:
            return
    proc.terminate()
    try:
        proc.wait(timeout=15)
    except subprocess.TimeoutExpired:
        proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass


def erro_idebras_instavel(exc: BaseException | str) -> bool:
    texto = str(exc).lower()
    return "http 50" in texto or "internal server error" in texto


def _erro_saida(nome: str, codigo: int | None) -> RuntimeError:
    if codigo == CODIGO_IDEBRAS_500:
        return RuntimeError(
            "O Idebras (http://andreserver:5050) retornou HTTP 500 ao abrir a "
            "Revisão do Parecer. O servidor interno falhou. "
            "Tente de novo em alguns minutos."
        )
    return RuntimeError(f"{nome} encerrou com código {codigo}.")


def _rodar_modulo(
    modulo: str,
    *,
    env: dict[str, str],
    timeout: float,
    nome: str,
) -> None:
    logger.info("Processo isolado %s (timeout %ss)", nome, int(timeout))
    try:
        proc = subprocess.Popen(
            [sys.executable, "-m", modulo],
            cwd=str(ROOT_DIR),
            env=env,
            creationflags=_flags_criacao(),
        )
    except OSError as exc:
        raise RuntimeError(f"Não foi possível iniciar {nome}: {exc}") from exc
    logger.info("%s iniciado (pid=%s)", nome, proc.pid)
    try:
        codigo = proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        logger.error("%s travado após %ss — encerrando processo.", nome, int(timeout))
        _encerrar(proc)
        raise TimeoutError(
            f"{nome} excedeu {int(timeout)} segundos "
            "(pasta de rede ou Idebras sem resposta)."
        ) from None
    if codigo not in (0, None):
        raise _erro_saida(nome, codigo)


def rodar_download_horario(
    token: str,
    destinos: list[str],
    *,
    timeout: float,
) -> None:
    env = os.environ.copy()
    env["SLACK_BOT_TOKEN"] = token
    env["REVISAO_JOB_DESTINOS"] = json.dumps(destinos, ensure_ascii=False)
    _rodar_modulo(
        "bot.job_download_revisao",
        env=env,
        timeout=timeout,
        nome="revisao-download-horario",
    )


def rodar_download_horario_em_background(
    token: str,
    destinos: list[str],
    *,
    timeout: float,
    on_timeout: Any | None = None,
    on_erro: Any | None = None,
    on_ok: Any | None = None,
) -> threading.Thread:
    """Dispara o job horário em thread dedicada (o scheduler não fica bloqueado)."""

    def _alvo() -> None:
        try:
            rodar_download_horario(token, destinos, timeout=timeout)
        except TimeoutError as erro:
            logger.error("%s", erro)
            if on_timeout:
                try:
                    on_timeout(erro)
                except Exception:
                    logger.exception("Falha ao notificar timeout do download horário")
        except Exception as erro:
            if erro_idebras_instavel(erro):
                logger.info(
                    "Download horário da revisão: nenhuma revisão a "
                    "finalizar no Idebras (%s). Aviso no Slack omitido.",
                    erro,
                )
            else:
                logger.exception("Falha no download horário da revisão")
                if on_erro:
                    try:
                        on_erro(erro)
                    except Exception:
                        logger.exception("Falha ao notificar erro do download horário")
            return
        if on_ok:
            try:
                on_ok()
            except Exception:
                logger.exception("Falha no callback de sucesso do download horário")
        else:
            logger.info("Download horário da revisão concluído.")

    t = threading.Thread(
        target=_alvo,
        daemon=True,
        name="revisao-download-job",
    )
    t.start()
    return t


def rodar_comando_revisao(modo: str, *, timeout: float) -> dict[str, Any]:
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        delete=False,
        encoding="utf-8",
    )
    saida = handle.name
    handle.close()
    env = os.environ.copy()
    env["REVISAO_JOB_MODO"] = modo
    env["REVISAO_JOB_SAIDA"] = saida
    try:
        try:
            _rodar_modulo(
                "bot.job_revisao",
                env=env,
                timeout=timeout,
                nome=f"revisao-{modo}",
            )
        except RuntimeError as exc:
            dados = _ler_json(saida)
            if dados and dados.get("erro"):
                raise RuntimeError(str(dados["erro"])) from exc
            raise
        dados = _ler_json(saida)
        if not dados:
            raise RuntimeError(f"revisao-{modo} terminou sem devolver resultado.")
        if dados.get("status") != "ok":
            raise RuntimeError(str(dados.get("erro") or "falha na revisão"))
        return dados["resultado"]
    finally:
        Path(saida).unlink(missing_ok=True)


def _ler_json(caminho: str) -> dict[str, Any] | None:
    try:
        texto = Path(caminho).read_text(encoding="utf-8")
    except OSError:
        return None
    if not texto.strip():
        return None
    try:
        dados = json.loads(texto)
    except json.JSONDecodeError:
        return None
    return dados if isinstance(dados, dict) else None
