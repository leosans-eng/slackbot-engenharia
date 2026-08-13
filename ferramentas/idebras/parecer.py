"""Download do Parecer Técnico (PDF) via HTTP."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from urllib.parse import unquote

from ferramentas.idebras.aspnet import AspNetSession
from ferramentas.idebras.fluxo import (
    FLUXO_PATH,
    abrir_detalhe_fluxo,
    payload_detalhe,
)

logger = logging.getLogger(__name__)

PARECER_PDF_RE = re.compile(
    r"split\('/'\)\[0\]\s*\+\s*['\"]([^'\"]+\.pdf)['\"]",
    re.I,
)
PARECER_ANEXO_RE = re.compile(
    r"/ANEXOS/[^\"'<>]+\.pdf",
    re.I,
)
PARECER_AUSENTE_RE = re.compile(
    r"arquivo do parecer n[aã]o encontrado",
    re.I,
)


def _nome_arquivo_seguro(nome: str) -> str:
    nome = re.sub(r'[<>:"/\\|?*]', "-", nome)
    nome = re.sub(r"\s+", " ", nome).strip()
    return nome or "parecer.pdf"


def _extrair_url_pdf(html: str) -> str | None:
    match = PARECER_PDF_RE.search(html)
    if match:
        return match.group(1)
    match = PARECER_ANEXO_RE.search(html)
    if match:
        return match.group(0)
    return None


def download_owner_parecer(
    owner_name: str,
    pdf_path: Path,
    *,
    result_index: int | None = None,
    session: AspNetSession | None = None,
) -> Path:
    """Login → Fluxo → Ver Informações → Parecer Técnico → PDF em pdf_path."""
    session, html, _chosen = abrir_detalhe_fluxo(
        owner_name,
        result_index=result_index,
        session=session,
        comando="parecer",
    )

    if not re.search(r"btnvisualizarparecer|parecer\s*t[eé]cnico", html, re.I):
        raise RuntimeError(
            'Após "Ver Informações" não apareceu "Parecer Técnico". '
            "A estrutura da página pode ter mudado."
        )

    logger.info('Abrindo "Parecer Técnico"...')
    _url, data, ctype = session.post(
        FLUXO_PATH,
        payload_detalhe(
            html, {"ctl00$body$btnvisualizarparecer": "Parecer Técnico"}
        ),
        timeout=120,
    )

    if data[:4] == b"%PDF" or "pdf" in (ctype or "").lower():
        dest = Path(pdf_path)
        if dest.suffix.lower() != ".pdf":
            dest = dest.with_suffix(".pdf")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        logger.info("PDF salvo em: %s", dest)
        return dest

    html = data.decode("utf-8", errors="replace")
    if PARECER_AUSENTE_RE.search(html):
        raise ValueError(
            f'Não há arquivo de parecer técnico para *{owner_name}*.'
        )

    pdf_url = _extrair_url_pdf(html)
    if not pdf_url:
        raise RuntimeError(
            'Resposta de "Parecer Técnico" não trouxe o PDF. '
            "A estrutura da página pode ter mudado."
        )

    logger.info("Baixando parecer %s...", pdf_url)
    _, data, ctype = session.get(pdf_url)
    if data[:4] != b"%PDF" and "pdf" not in ctype.lower() and "octet" not in ctype.lower():
        raise RuntimeError(
            f"Download de {pdf_url} não parece PDF (Content-Type={ctype!r})."
        )

    dest = Path(pdf_path)
    remote_name = Path(unquote(pdf_url)).name
    if remote_name.lower().endswith(".pdf"):
        dest = dest.with_name(_nome_arquivo_seguro(remote_name))
    elif dest.suffix.lower() != ".pdf":
        dest = dest.with_suffix(".pdf")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    logger.info("PDF salvo em: %s", dest)
    return dest
