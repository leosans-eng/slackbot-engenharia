"""Utilitários de integração com o sistema operacional."""

from __future__ import annotations

import os
import subprocess
import sys


def abrir_arquivo(caminho: str) -> None:
    """Abre um arquivo no aplicativo padrão do sistema."""
    caminho_absoluto = os.path.abspath(caminho)
    if sys.platform == "win32":
        os.startfile(caminho_absoluto)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.run(["open", caminho_absoluto], check=False)
    else:
        subprocess.run(["xdg-open", caminho_absoluto], check=False)
