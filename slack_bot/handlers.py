"""Handlers do bot Slack (esqueleto para implementação futura)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from formatador import Modelo, formatar_planilha
from formatador.types import ResultadoFormatacao


def processar_upload(
    caminho_entrada: str,
    modelo: Modelo | int,
    diretorio_saida: str | None = None,
) -> ResultadoFormatacao:
    """
    Processa uma planilha recebida pelo Slack.

    Use um diretório temporário para entrada/saída quando o bot estiver em produção.
    """
    saida = diretorio_saida or tempfile.mkdtemp(prefix="formatador-slack-")
    os.makedirs(saida, exist_ok=True)
    return formatar_planilha(
        caminho_entrada,
        modelo=modelo,
        diretorio_saida=saida,
    )


def arquivos_para_enviar(resultado: ResultadoFormatacao) -> list[Path]:
    """Lista os arquivos gerados que devem ser enviados de volta ao Slack."""
    arquivos = [Path(resultado.caminho_excel)]
    if resultado.caminho_word:
        arquivos.append(Path(resultado.caminho_word))
    return arquivos
