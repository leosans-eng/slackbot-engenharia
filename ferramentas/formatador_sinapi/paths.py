"""Caminhos do pacote em relação à raiz do projeto."""

from __future__ import annotations

import os

RAIZ_PROJETO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
DIR_MODELOS = os.path.join(RAIZ_PROJETO, "modelos")


def caminho_modelo_word(nome_arquivo: str) -> str:
    return os.path.join(DIR_MODELOS, nome_arquivo)
