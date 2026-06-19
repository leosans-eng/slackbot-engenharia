"""Resolução do arquivo de entrada para uso local (CLI)."""

from __future__ import annotations

import os
from pathlib import Path

PREFIXO_SAIDA = "Planilha_Sintetica_Convertida_Modelo"
PADROES_ENTRADA = (
    "Planilha Sintética Simples*.xlsx",
    "Planilha Sintética*.xlsx",
)


class ArquivoEntradaAmbiguo(Exception):
    """Vários arquivos candidatos encontrados na pasta."""

    def __init__(self, candidatos: list[Path]):
        self.candidatos = candidatos
        nomes = "\n".join(f"  - {caminho.name}" for caminho in candidatos)
        super().__init__(
            "Vários arquivos de entrada encontrados. Informe o caminho na linha de comando:\n"
            f"{nomes}"
        )


def _eh_arquivo_saida(caminho: Path) -> bool:
    return caminho.name.startswith(PREFIXO_SAIDA)


def _candidatos_na_pasta(diretorio: Path) -> list[Path]:
    encontrados: dict[Path, None] = {}
    for padrao in PADROES_ENTRADA:
        for caminho in diretorio.glob(padrao):
            if caminho.is_file() and not _eh_arquivo_saida(caminho):
                encontrados[caminho.resolve()] = None
    return sorted(
        encontrados.keys(),
        key=lambda caminho: caminho.stat().st_mtime,
        reverse=True,
    )


def _carregar_local_config() -> str | None:
    try:
        import local_config
    except ImportError:
        return None

    valor = getattr(local_config, "ARQUIVO_ENTRADA", None)
    if valor is None:
        return None
    valor = str(valor).strip()
    return valor or None


def resolver_arquivo_entrada(
    caminho_informado: str | None = None,
    *,
    diretorio: str | Path | None = None,
) -> tuple[str, str]:
    """
    Define qual planilha usar na CLI local.

    Ordem de prioridade:
    1. Argumento informado na linha de comando
    2. Variável de ambiente SLACKBOT_ARQUIVO_ENTRADA
    3. Arquivo local_config.py (ARQUIVO_ENTRADA)
    4. Detecção automática na pasta do projeto
    """
    if caminho_informado:
        return os.path.abspath(caminho_informado), "informado na linha de comando"

    env = (os.environ.get("SLACKBOT_ARQUIVO_ENTRADA") or os.environ.get("FORMATADOR_ARQUIVO_ENTRADA") or "").strip()
    if env:
        return os.path.abspath(env), "variável SLACKBOT_ARQUIVO_ENTRADA"

    config = _carregar_local_config()
    if config:
        return os.path.abspath(config), "local_config.py"

    base = Path(diretorio or os.getcwd())
    candidatos = _candidatos_na_pasta(base)
    if not candidatos:
        raise FileNotFoundError(
            "Nenhuma planilha de entrada encontrada.\n"
            "Coloque um arquivo 'Planilha Sintética*.xlsx' na pasta do projeto, "
            "informe o caminho (python scripts/formatar_modelo1.py arquivo.xlsx) ou configure "
            "local_config.py (veja local_config.example.py)."
        )
    if len(candidatos) > 1:
        raise ArquivoEntradaAmbiguo(candidatos)

    return str(candidatos[0]), "detectado automaticamente na pasta"
