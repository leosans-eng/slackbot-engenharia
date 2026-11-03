"""Instaladores publicados no GitHub para os programas do escritório."""

from __future__ import annotations

import json
import logging
import re
import shutil
import uuid
import urllib.error
import urllib.request
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_USER_AGENT = "slackbot-engenharia"
_TAG = re.compile(r"^v?\d[\w.\-]{0,40}$")


@dataclass(frozen=True)
class Programa:
    codigo: str
    sigla: str
    nome: str
    repositorio: str


@dataclass(frozen=True)
class ReleasePrograma:
    codigo: str
    sigla: str
    nome: str
    versao: str
    notas: str
    html_url: str
    arquivo_nome: str
    arquivo_url: str

    @property
    def tem_notas(self) -> bool:
        return bool(self.notas.strip())


PROGRAMAS: dict[str, Programa] = {
    "orc": Programa(
        "orc",
        "ORC",
        "Orçamentos de Reparos Construtivos",
        "leosans-eng/orcamentos-reparos-construtivos",
    ),
    "grf": Programa(
        "grf",
        "GRF",
        "Gerador de Relatórios Fotográficos",
        "leosans-eng/gerador-relatorios-fotograficos",
    ),
}


def obter_release(codigo: str, versao: str | None = None) -> ReleasePrograma:
    """Última release, ou a tag pedida, com o instalador .exe."""
    programa = PROGRAMAS.get(codigo)
    if programa is None:
        raise ValueError("Não conheço esse programa.")
    if versao is not None and not _TAG.fullmatch(versao):
        raise ValueError("Não consegui identificar a versão.")
    caminho = "releases/latest" if not versao else f"releases/tags/{versao}"
    url = f"https://api.github.com/repos/{programa.repositorio}/{caminho}"
    dados = _json(url, programa)
    tag = str(dados.get("tag_name") or "").strip()
    if not tag or not _TAG.fullmatch(tag):
        raise ValueError(f"A versão publicada do {programa.sigla} veio sem identificação.")
    asset = _escolher_instalador(dados.get("assets") or [], programa)
    arquivo_url = str(asset.get("browser_download_url") or "")
    prefixo = f"https://github.com/{programa.repositorio}/releases/download/"
    if not arquivo_url.startswith(prefixo):
        raise ValueError(f"O instalador do {programa.sigla} não tem um link esperado.")
    return ReleasePrograma(
        codigo=programa.codigo,
        sigla=programa.sigla,
        nome=programa.nome,
        versao=tag,
        notas=str(dados.get("body") or ""),
        html_url=str(dados.get("html_url") or f"https://github.com/{programa.repositorio}/releases/tag/{tag}"),
        arquivo_nome=_nome_seguro(str(asset.get("name") or "instalador.exe")),
        arquivo_url=arquivo_url,
    )


def formatar_novidades(release: ReleasePrograma) -> str:
    """Notas da versão em mrkdwn."""
    corpo = release.notas.replace("\r\n", "\n").replace("\r", "\n").strip()
    corpo = re.sub(r"\*\*(.+?)\*\*", r"*\1*", corpo)
    corpo = re.sub(r"^#{1,6}\s*", "", corpo, flags=re.M)
    corpo = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r"<\2|\1>", corpo)
    titulo = f"*{release.sigla}* {release.versao}"
    if not corpo:
        return f"{titulo} não tem notas publicadas."
    texto = f"{titulo}\n{corpo}"
    if len(texto) > 2800:
        texto = texto[:2700].rstrip() + "\n…"
    return texto


@contextmanager
def instalador_baixado(
    release: ReleasePrograma,
    diretorio_temporario: str,
) -> Iterator[Path]:
    pasta = Path(diretorio_temporario) / f"programa-{uuid.uuid4().hex}"
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        destino = pasta / release.arquivo_nome
        _baixar(release.arquivo_url, destino)
        yield destino
    finally:
        shutil.rmtree(pasta, ignore_errors=True)


def _escolher_instalador(assets: list, programa: Programa) -> dict:
    exes = [
        asset
        for asset in assets
        if isinstance(asset, dict)
        and str(asset.get("name") or "").lower().endswith(".exe")
    ]
    if not exes:
        raise ValueError(f"A última versão do {programa.sigla} não tem instalador.")

    def ordem(asset: dict) -> tuple[int, str]:
        nome = str(asset.get("name") or "").lower()
        preferido = 0 if ("instal" in nome or "setup" in nome) else 1
        return preferido, nome

    return sorted(exes, key=ordem)[0]


def _json(url: str, programa: Programa) -> dict:
    try:
        with _abrir(url) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib.error.HTTPError as erro:
        if erro.code == 404:
            raise ValueError(f"Não há versão publicada do {programa.sigla}.") from erro
        raise ValueError(
            f"O GitHub respondeu {erro.code} ao buscar o {programa.sigla}."
        ) from erro
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as erro:
        raise ValueError(
            f"Não consegui falar com o GitHub para buscar o {programa.sigla}."
        ) from erro
    if not isinstance(dados, dict):
        raise ValueError(f"A resposta do GitHub sobre o {programa.sigla} veio incompleta.")
    return dados


def _baixar(url: str, destino: Path) -> None:
    try:
        with _abrir(url, timeout=180, accept="*/*") as resposta, destino.open("wb") as arquivo:
            while True:
                bloco = resposta.read(256 * 1024)
                if not bloco:
                    break
                arquivo.write(bloco)
    except (urllib.error.URLError, TimeoutError, OSError) as erro:
        raise ValueError("Não consegui baixar o instalador.") from erro
    if not destino.is_file() or destino.stat().st_size <= 0:
        raise ValueError("O instalador baixado veio vazio.")


def _abrir(url: str, timeout: int = 30, accept: str = "application/vnd.github+json"):
    pedido = urllib.request.Request(
        url,
        headers={
            "Accept": accept,
            "User-Agent": _USER_AGENT,
        },
    )
    return urllib.request.urlopen(pedido, timeout=timeout)


def _nome_seguro(nome: str) -> str:
    base = Path(nome).name
    limpo = re.sub(r'[<>:"/\\|?*]', "-", base).strip()
    return limpo or "instalador.exe"
