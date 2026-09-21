"""Logging que não trava o bot se o console do Windows congelar (Quick Edit)."""

from __future__ import annotations

import atexit
import logging
import logging.handlers
import queue
import sys
from typing import Any

_listener: logging.handlers.QueueListener | None = None


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
    """Console via fila: workers do Slack não bloqueiam se o cmd travar na escrita."""
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

    _listener = logging.handlers.QueueListener(
        fila, console, respect_handler_level=True
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
