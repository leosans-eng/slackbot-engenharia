"""Download de fotos do imóvel via HTTP (sem Playwright)."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
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

logger = logging.getLogger(__name__)

TEMP_ZIP = re.compile(r"/Temp/[0-9a-fA-F\-]+\.zip")
GALERIA_URL_RE = re.compile(
    r"/GaleriaFotos\?[^\"'\s<>]+",
    re.I,
)

ProgressCallback = Callable[[str], None]

__all__ = [
    "FluxoResult",
    "MultiplosResultadosError",
    "download_owner_photos",
    "listar_resultados_fluxo",
]


def _photo_indices(fields: dict[str, str]) -> list[str]:
    idxs: list[str] = []
    for name in fields:
        m = re.fullmatch(r"rpGaleriaFotos\$ctl(\d+)\$hfidfoto", name)
        if m:
            idxs.append(m.group(1))
    idxs.sort(key=lambda x: int(x))
    return idxs


def download_owner_photos(
    owner_name: str,
    zip_path: Path,
    *,
    result_index: int | None = None,
    session: AspNetSession | None = None,
    on_progress: ProgressCallback | None = None,
) -> Path:
    """Login → Fluxo → Ver Informações → Galeria → ZIP em zip_path."""
    session, html, _chosen = abrir_detalhe_fluxo(
        owner_name,
        result_index=result_index,
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
        payload = dict(fields)
        payload["__EVENTTARGET"] = ""
        payload["__EVENTARGUMENT"] = ""
        payload["btnmostrarmaisfotos"] = "Mostrar Mais"
        payload.pop("btndownloadfoto", None)
        payload.pop("__ASYNCPOST", None)
        payload.pop("ScriptMaster", None)

        html = session.post_html(galeria_url, payload)
        fields = parse_form_fields(html)
        rounds += 1
        after = len(_photo_indices(fields))
        if after <= before:
            break

    idxs = _photo_indices(fields)
    if not idxs:
        raise RuntimeError("Nenhuma foto (hfidfoto) encontrada na galeria.")

    logger.info("Marcando %s foto(s) e baixando ZIP...", len(idxs))
    if on_progress:
        on_progress(f"Preparando download ({len(idxs)} fotos)…")
    payload = dict(fields)
    payload["__EVENTTARGET"] = ""
    payload["__EVENTARGUMENT"] = ""
    payload.pop("btnmostrarmaisfotos", None)
    payload.pop("ScriptMaster", None)
    payload.pop("__ASYNCPOST", None)
    for idx in idxs:
        payload[f"rpGaleriaFotos$ctl{idx}$cbimovel"] = "on"
    payload["btndownloadfoto"] = "Download"

    html = session.post_html(galeria_url, payload)
    match = TEMP_ZIP.search(html)
    if not match:
        raise RuntimeError(
            "Resposta do Download não trouxe link /Temp/*.zip. "
            "Verifique se as fotos foram marcadas corretamente."
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
