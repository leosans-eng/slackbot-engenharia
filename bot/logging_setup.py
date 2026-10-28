"""Logging que não trava o bot se o console do Windows congelar (Quick Edit)."""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import queue
import sys
from pathlib import Path
from typing import Any

_listener: logging.handlers.QueueListener | None = None
ROOT_DIR = Path(__file__).resolve().parent.parent


def _desativar_quick_edit_windows() -> None:
    """Evita o freeze clássico do cmd.exe ao clicar na janela (seleção de texto)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        if handle in (0, -1):
            return
        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            return
        enable_extended_flags = 0x0080
        enable_quick_edit = 0x0040
        novo = (mode.value | enable_extended_flags) & ~enable_quick_edit
        kernel32.SetConsoleMode(handle, novo)
    except Exception:
        pass


def configurar_logging(*, nivel: int = logging.INFO) -> Any:
    """Console via fila + arquivo em logs/bot.log (respostas de /fotos etc.)."""
    global _listener

    _desativar_quick_edit_windows()

    formato = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    fila: queue.Queue[logging.LogRecord] = queue.Queue(-1)

    raiz = logging.getLogger()
    raiz.setLevel(nivel)
    for handler in list(raiz.handlers):
        raiz.removeHandler(handler)

    raiz.addHandler(logging.handlers.QueueHandler(fila))

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(formato)
    console.setLevel(nivel)

    logs_dir = ROOT_DIR / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    arquivo = logging.handlers.TimedRotatingFileHandler(
        logs_dir / "bot.log",
        when="midnight",
        backupCount=45,
        encoding="utf-8",
    )
    arquivo.setFormatter(formato)
    arquivo.setLevel(nivel)

    _listener = logging.handlers.QueueListener(
        fila, console, arquivo, respect_handler_level=True
    )
    _listener.start()
    atexit.register(_parar_listener)
    return _listener


def _parar_listener() -> None:
    global _listener
    if _listener is not None:
        try:
            _listener.stop()
        except Exception:
            pass
        _listener = None
