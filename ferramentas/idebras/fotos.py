"""Download de fotos do imóvel via HTTP (sem Playwright)."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from ferramentas.idebras.aspnet import (
    AspNetSession,
    parse_form_fields,
)
from ferramentas.idebras.fluxo import (
    FLUXO_PATH,
    FluxoResult,
    MultiplosResultadosError,
    abrir_detalhe_fluxo,
    listar_resultados_fluxo,
    payload_detalhe,
)
from ferramentas.idebras.pdf import IMAGE_EXTENSIONS

logger = logging.getLogger(__name__)

TEMP_ZIP = re.compile(r"/Temp/[0-9a-fA-F\-]+\.zip")
GALERIA_URL_RE = re.compile(
    r"/GaleriaFotos\?[^\"'\s<>]+",
    re.I,
)

ProgressCallback = Callable[[str], None]

__all__ = [
    "FluxoResult",
    "ItemGaleria",
    "MultiplosResultadosError",
    "PacoteFotos",
    "download_arquivos_extras",
    "download_owner_photos",
    "listar_resultados_fluxo",
]

_CHECKBOX = re.compile(r"rpGaleriaFotos\$ctl(\d+)\$cbimovel$")
_HFID = re.compile(r"rpGaleriaFotos\$ctl(\d+)\$hfidfoto$")


@dataclass(frozen=True)
class ItemGaleria:
    indice: str
    nome: str
    tipo: str


@dataclass(frozen=True)
class PacoteFotos:
    """ZIP só com fotos, nomes de outros arquivos e quantos PDFs ficaram de fora."""

    zip_path: Path | None
    extras: list[str]
    pdfs_ignorados: int


def classificar_arquivo(nome: str, tipo_mime: str = "") -> str:
    """'imagem' entra no ZIP. 'pdf' nunca é selecionado. O resto é perguntado."""
    ext = Path(nome or "").suffix.lower()
    mime = (tipo_mime or "").split(";")[0].strip().lower()
    if ext == ".pdf" or mime == "application/pdf":
        return "pdf"
    if ext in IMAGE_EXTENSIONS or mime.startswith("image/"):
        return "imagem"
    return "outro"


def _photo_indices(fields: dict[str, str]) -> list[str]:
    idxs: list[str] = []
    for name in fields:
        m = re.fullmatch(r"rpGaleriaFotos\$ctl(\d+)\$hfidfoto", name)
        if m:
            idxs.append(m.group(1))
    idxs.sort(key=lambda x: int(x))
    return idxs


def _catalogo_galeria(fields: dict[str, str]) -> dict[str, tuple[str, str]]:
    bruto = fields.get("galeriaArquivo") or ""
    if not bruto.strip():
        return {}
    try:
        itens = json.loads(bruto)
    except json.JSONDecodeError:
        logger.warning("galeriaArquivo não é JSON; não dá para separar PDF e vídeo.")
        return {}
    catalogo: dict[str, tuple[str, str]] = {}
    if not isinstance(itens, list):
        return {}
    for item in itens:
        if not isinstance(item, dict):
            continue
        fid = str(item.get("idfotoanalise") or "").strip()
        nome = str(item.get("nomefoto") or "").strip()
        if not fid:
            continue
        catalogo[fid] = (nome, classificar_arquivo(nome, str(item.get("tipofoto") or "")))
    return catalogo


def _itens_galeria(
    fields: dict[str, str],
    catalogo: dict[str, tuple[str, str]],
) -> list[ItemGaleria]:
    itens: list[ItemGaleria] = []
    for name, valor in fields.items():
        match = _HFID.fullmatch(name)
        if not match:
            continue
        info = catalogo.get(str(valor))
        if info is None:
            itens.append(ItemGaleria(match.group(1), "", "desconhecido"))
        else:
            itens.append(ItemGaleria(match.group(1), info[0], info[1]))
    itens.sort(key=lambda item: int(item.indice))
    return itens


def _sem_checkboxes(fields: dict[str, str]) -> dict[str, str]:
    return {nome: valor for nome, valor in fields.items() if not _CHECKBOX.fullmatch(nome)}


def _marcar(fields: dict[str, str], indices: list[str]) -> dict[str, str]:
    payload = _sem_checkboxes(fields)
    payload["__EVENTTARGET"] = ""
    payload["__EVENTARGUMENT"] = ""
    payload.pop("btnmostrarmaisfotos", None)
    payload.pop("ScriptMaster", None)
    payload.pop("__ASYNCPOST", None)
    for indice in indices:
        payload[f"rpGaleriaFotos$ctl{indice}$cbimovel"] = "on"
    payload["btndownloadfoto"] = "Download"
    return payload


def _salvar_zip(session: AspNetSession, html: str, zip_path: Path, on_progress) -> Path:
    match = TEMP_ZIP.search(html)
    if not match:
        raise RuntimeError(
            "Resposta do Download não trouxe link /Temp/*.zip. "
            "Verifique se as imagens realmente estão salvas no Idebras."
        )
    temp_path = match.group(0)
    logger.info("Baixando %s...", temp_path)
    if on_progress:
        on_progress("Baixando ZIP…")
    _, data, ctype = session.get(temp_path)
    if data[:2] != b"PK" and "zip" not in ctype.lower() and "octet" not in ctype.lower():
        raise RuntimeError(
            f"Download de {temp_path} não parece ZIP (Content-Type={ctype!r})."
        )
    zip_path = Path(zip_path)
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(data)
    logger.info("ZIP salvo em: %s", zip_path)
    return zip_path


def _abrir_galeria(
    owner_name: str,
    *,
    result_index: int | None,
    processo: str | None,
    session: AspNetSession | None,
    on_progress: ProgressCallback | None,
) -> tuple[AspNetSession, str, dict[str, str], list[ItemGaleria]]:
    session, html, _chosen = abrir_detalhe_fluxo(
        owner_name,
        result_index=result_index,
        processo=processo,
        session=session,
        comando="fotos",
        on_progress=on_progress,
    )

    if not re.search(r"fotos\s*im[oó]vel|btnfotosimovel", html, re.I):
        if not re.search(r"visualizar\s*fotos|btnfotosimovel", html, re.I):
            raise RuntimeError(
                'Após "Ver Informações" não apareceu "Fotos Imóvel". '
                "A estrutura da página pode ter mudado."
            )

    logger.info('Abrindo "Fotos Imóvel"...')
    if on_progress:
        on_progress("Abrindo fotos do imóvel…")
    html = session.post_html(
        FLUXO_PATH,
        payload_detalhe(html, {"ctl00$body$btnfotosimovel": "Fotos Imóvel"}),
    )

    match = GALERIA_URL_RE.search(html)
    if not match:
        raise RuntimeError(
            'Resposta de "Fotos Imóvel" não trouxe URL /GaleriaFotos?idimovel=...'
        )
    galeria_url = match.group(0)
    logger.info("Abrindo galeria de fotos (%s)...", galeria_url)
    if on_progress:
        on_progress("Carregando galeria…")
    html = session.get_html(galeria_url)
    fields = parse_form_fields(html)
    catalogo = _catalogo_galeria(fields)
    if not _photo_indices(fields) and "galeriaArquivo" not in fields:
        raise RuntimeError(
            "GaleriaFotos não trouxe fotos. O imóvel pode não ter imagens."
        )

    rounds = 0
    while rounds < 50 and "btnmostrarmaisfotos" in html.lower():
        before = len(_photo_indices(fields))
        logger.info("Expandindo fotos (Mostrar Mais)... (%s ids)", before)
        if on_progress and (rounds == 0 or rounds % 3 == 0):
            on_progress(f"Carregando fotos… ({before} encontradas)")
        payload = _sem_checkboxes(fields)
        payload["__EVENTTARGET"] = ""
        payload["__EVENTARGUMENT"] = ""
        payload["btnmostrarmaisfotos"] = "Mostrar Mais"
        payload.pop("btndownloadfoto", None)
        payload.pop("__ASYNCPOST", None)
        payload.pop("ScriptMaster", None)
        html = session.post_html(galeria_url, payload)
        fields = parse_form_fields(html)
        catalogo = _catalogo_galeria(fields) or catalogo
        rounds += 1
        after = len(_photo_indices(fields))
        if after <= before:
            break

    if not catalogo:
        raise RuntimeError(
            "A galeria não informou o tipo de cada arquivo. "
            "Não selecionei nada para não incluir PDF."
        )
    itens = _itens_galeria(fields, catalogo)
    if not itens:
        raise RuntimeError("Nenhuma foto (hfidfoto) encontrada na galeria.")
    return session, galeria_url, fields, itens


def _baixar_tipos(
    owner_name: str,
    zip_path: Path,
    tipos: set[str],
    *,
    result_index: int | None,
    processo: str | None,
    session: AspNetSession | None,
    on_progress: ProgressCallback | None,
) -> tuple[Path | None, list[ItemGaleria]]:
    session, galeria_url, fields, itens = _abrir_galeria(
        owner_name,
        result_index=result_index,
        processo=processo,
        session=session,
        on_progress=on_progress,
    )
    escolhidos = [item for item in itens if item.tipo in tipos and item.nome]
    if not escolhidos:
        return None, itens
    logger.info(
        "Marcando %s arquivo(s) (%s) e baixando ZIP...",
        len(escolhidos),
        ", ".join(sorted(tipos)),
    )
    if on_progress:
        on_progress(f"Preparando download ({len(escolhidos)} arquivos)…")
    html = session.post_html(
        galeria_url,
        _marcar(fields, [item.indice for item in escolhidos]),
    )
    return _salvar_zip(session, html, zip_path, on_progress), itens


def download_owner_photos(
    owner_name: str,
    zip_path: Path,
    *,
    result_index: int | None = None,
    processo: str | None = None,
    session: AspNetSession | None = None,
    on_progress: ProgressCallback | None = None,
) -> PacoteFotos:
    """Login → galeria. Baixa só imagens. PDF fica de fora; o resto volta em extras."""
    salvo, itens = _baixar_tipos(
        owner_name,
        zip_path,
        {"imagem"},
        result_index=result_index,
        processo=processo,
        session=session,
        on_progress=on_progress,
    )
    extras = [item.nome for item in itens if item.tipo == "outro" and item.nome]
    pdfs = sum(1 for item in itens if item.tipo == "pdf")
    desconhecidos = sum(1 for item in itens if item.tipo == "desconhecido")
    if desconhecidos:
        logger.warning(
            "Galeria: %s arquivo(s) sem tipo conhecido ficaram de fora.",
            desconhecidos,
        )
    logger.info(
        "Galeria: %s foto(s), %s PDF(s) de fora, %s outro(s).",
        sum(1 for item in itens if item.tipo == "imagem"),
        pdfs,
        len(extras),
    )
    return PacoteFotos(zip_path=salvo, extras=extras, pdfs_ignorados=pdfs)


def download_arquivos_extras(
    owner_name: str,
    zip_path: Path,
    *,
    result_index: int | None = None,
    processo: str | None = None,
    session: AspNetSession | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Baixa só o que não é foto nem PDF (vídeo e outros formatos)."""
    salvo, _itens = _baixar_tipos(
        owner_name,
        zip_path,
        {"outro"},
        result_index=result_index,
        processo=processo,
        session=session,
        on_progress=on_progress,
    )
    if salvo is None:
        raise RuntimeError("Não há vídeo nem outro arquivo para baixar nesta galeria.")
    return salvo
