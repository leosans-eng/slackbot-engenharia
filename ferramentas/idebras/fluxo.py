"""Pesquisa de imóveis no Controle de Fluxo de Trabalho (Idebras)."""

from __future__ import annotations

import html as html_lib
import logging
import re
from dataclasses import dataclass

from ferramentas.idebras.aspnet import (
    AspNetSession,
    login,
    parse_form_fields,
    parse_hidden_fields,
)
from ferramentas.idebras.config import FLUXO_URL

logger = logging.getLogger(__name__)

FLUXO_PATH = "/FluxoTrabalho/ControleFluxoTrabalho"
VER_INFO_RE = re.compile(r"ver\s*informa[cç][oõ]es", re.I)
GRID_BTN = re.compile(
    r'name=["\'](ctl00\$body\$gridfluxo\$ctl\d+\$ctl\d+)["\'][^>]*value=["\']([^"\']*)["\']'
    r"|value=[\"']([^\"']*)[\"'][^>]*name=[\"'](ctl00\$body\$gridfluxo\$ctl\d+\$ctl\d+)[\"']",
    re.I,
)
STRIP_TAGS = re.compile(r"<[^>]+>")
HEADER_HINTS = ("mutuário", "mutuario", "situação atual", "situacao atual", "usuário atual")

FLUXO_SEARCH_KEYS = (
    "__EVENTARGUMENT",
    "__EVENTTARGET",
    "__EVENTVALIDATION",
    "__SCROLLPOSITIONX",
    "__SCROLLPOSITIONY",
    "__VIEWSTATE",
    "__VIEWSTATEENCRYPTED",
    "__VIEWSTATEGENERATOR",
    "ctl00$body$cbexibirfluxobaixados",
    "ctl00$body$dropconjuntopesquisa",
    "ctl00$body$dropetapaservico",
    "ctl00$body$dropfuncionario",
    "ctl00$body$dropfuncionariocentral",
    "ctl00$body$dropfuncionariopesquisa",
    "ctl00$body$dropsituacaofluxopesquisa",
    "ctl00$body$txtcpfcliente",
    "ctl00$body$txtnomecliente",
    "ctl00$body$txtnomemutuariopesquisa",
    "ctl00$body$txtobservacaodevolver",
    "ctl00$body$txtobservacaofinal",
    "ctl00$body$txtobservacaofinalizarfluxo",
    "ctl00$body$txtpesquisaimovelnome",
)


@dataclass
class FluxoResult:
    button_name: str
    label: str
    dedupe_key: str


class MultiplosResultadosError(ValueError):
    """Vários imóveis encontrados; o usuário precisa escolher um índice."""

    def __init__(
        self,
        owner_name: str,
        results: list[FluxoResult],
        *,
        comando: str = "fotos",
    ) -> None:
        self.owner_name = owner_name
        self.results = results
        self.comando = comando
        linhas = [
            f'Encontrei *{len(results)}* imóveis para "{owner_name}". Escolha um com:',
            f"`/{comando} {owner_name} opcao=N`",
            f"(também vale `/{comando} {owner_name} N`)",
            "",
        ]
        for i, item in enumerate(results, start=1):
            preview = item.label if len(item.label) <= 100 else item.label[:97] + "..."
            linhas.append(f"  *[{i}]* {preview}")
        super().__init__("\n".join(linhas))


def _dedupe_key(text: str) -> str:
    match = re.search(r"\((\d+)\)", text)
    return match.group(1) if match else text


def _is_header_row(text: str) -> bool:
    lower = text.lower()
    if VER_INFO_RE.search(text):
        return False
    return sum(1 for hint in HEADER_HINTS if hint in lower) >= 2


def _row_text_for_button(html: str, button_name: str) -> str:
    escaped = re.escape(button_name)
    row_re = re.compile(
        rf"<tr[^>]*>(?:(?!</tr>).)*{escaped}(?:(?!</tr>).)*</tr>",
        re.I | re.S,
    )
    m = row_re.search(html)
    if not m:
        return button_name
    text = STRIP_TAGS.sub(" ", m.group(0))
    return html_lib.unescape(" ".join(text.split()))


def parse_ver_info_results(html: str) -> list[FluxoResult]:
    found: list[FluxoResult] = []
    seen: set[str] = set()
    for m in GRID_BTN.finditer(html):
        if m.group(1) is not None:
            name, value = m.group(1), m.group(2)
        else:
            name, value = m.group(4), m.group(3)
        if not VER_INFO_RE.search(value or ""):
            continue
        label = _row_text_for_button(html, name)
        if not label or _is_header_row(label):
            continue
        key = _dedupe_key(label)
        if key in seen:
            continue
        seen.add(key)
        found.append(FluxoResult(button_name=name, label=label, dedupe_key=key))
    return found


def _pick_result(
    owner_name: str,
    results: list[FluxoResult],
    result_index: int | None,
    *,
    comando: str = "fotos",
) -> FluxoResult:
    if not results:
        raise ValueError(
            'Nenhum resultado com "Ver Informações". '
            "Confira o nome do proprietário ou se há fluxos baixados."
        )
    if len(results) == 1:
        logger.info("Um resultado encontrado; abrindo automaticamente.")
        return results[0]

    if result_index is None:
        raise MultiplosResultadosError(owner_name, results, comando=comando)

    if not (1 <= result_index <= len(results)):
        raise ValueError(
            f"Opção `{result_index}` inválida. Há {len(results)} resultado(s). "
            f"Use um número entre 1 e {len(results)}."
        )

    return results[result_index - 1]


def _fluxo_payload(
    html: str,
    owner_name: str,
    *,
    extra: dict[str, str] | None = None,
) -> dict[str, str]:
    """Monta POST do ControleFluxoTrabalho só com keys aceitas pelo servidor."""
    parsed = parse_form_fields(html)
    hidden = parse_hidden_fields(html)
    defaults = {
        "__EVENTARGUMENT": "",
        "__EVENTTARGET": "",
        "__SCROLLPOSITIONX": "0",
        "__SCROLLPOSITIONY": "0",
        "ctl00$body$cbexibirfluxobaixados": "on",
        "ctl00$body$dropconjuntopesquisa": "TODOS",
        "ctl00$body$dropetapaservico": "SELECIONE",
        "ctl00$body$dropfuncionario": "SELECIONE",
        "ctl00$body$dropfuncionariocentral": "SELECIONE",
        "ctl00$body$dropfuncionariopesquisa": "SELECIONE",
        "ctl00$body$dropsituacaofluxopesquisa": "SELECIONE",
        "ctl00$body$txtcpfcliente": "",
        "ctl00$body$txtnomecliente": "",
        "ctl00$body$txtnomemutuariopesquisa": owner_name,
        "ctl00$body$txtobservacaodevolver": "",
        "ctl00$body$txtobservacaofinal": "",
        "ctl00$body$txtobservacaofinalizarfluxo": "",
        "ctl00$body$txtpesquisaimovelnome": "",
    }
    out: dict[str, str] = {}
    for key in FLUXO_SEARCH_KEYS:
        if key in hidden:
            out[key] = hidden[key]
        elif key in parsed:
            out[key] = parsed[key]
        elif key in defaults:
            out[key] = defaults[key]
        else:
            out[key] = ""
    out.update(defaults)
    for key in (
        "__VIEWSTATE",
        "__VIEWSTATEGENERATOR",
        "__EVENTVALIDATION",
        "__VIEWSTATEENCRYPTED",
    ):
        if key in hidden:
            out[key] = hidden[key]
    out["ctl00$body$txtnomemutuariopesquisa"] = owner_name
    out["ctl00$body$cbexibirfluxobaixados"] = "on"
    if extra:
        out.update(extra)
    return out


def payload_detalhe(html: str, extra: dict[str, str]) -> dict[str, str]:
    """POST da tela após 'Ver Informações' (Fotos Imóvel, Parecer Técnico, etc.)."""
    hidden = parse_hidden_fields(html)
    fields = {
        "__EVENTTARGET": "",
        "__EVENTARGUMENT": "",
        "__SCROLLPOSITIONX": "0",
        "__SCROLLPOSITIONY": "0",
        **hidden,
        "ctl00$body$txtobservacaofinal": "",
        "ctl00$body$txtnomecliente": "",
        "ctl00$body$txtcpfcliente": "",
        "ctl00$body$txtobservacaodevolver": "",
        "ctl00$body$txtobservacaofinalizarfluxo": "",
        "ctl00$body$txtpesquisaimovelnome": "",
        **extra,
    }
    parsed = parse_form_fields(html)
    for key in (
        "ctl00$body$dropetapaservico",
        "ctl00$body$dropfuncionario",
        "ctl00$body$dropfuncionariocentral",
    ):
        if key in parsed:
            fields[key] = parsed[key]
    return fields


def _pesquisar_fluxo(
    session: AspNetSession,
    owner_name: str,
) -> tuple[str, list[FluxoResult]]:
    html = session.get_html(FLUXO_PATH)
    if "txtnomemutuariopesquisa" not in html and "nomemutuario" not in html.lower():
        raise RuntimeError(
            f"Página inesperada em {FLUXO_URL}. Login pode ter expirado ou a URL mudou."
        )

    fields = _fluxo_payload(
        html,
        owner_name,
        extra={"ctl00$body$btnpesquisarfluxo": "Pesquisar"},
    )
    logger.info('Pesquisando proprietário "%s" (fluxos baixados)...', owner_name)
    html = session.post_html(FLUXO_PATH, fields)
    return html, parse_ver_info_results(html)


def listar_resultados_fluxo(
    owner_name: str,
    *,
    session: AspNetSession | None = None,
) -> list[FluxoResult]:
    """Login + pesquisa; retorna a lista de imóveis sem abrir o detalhe."""
    owner_name = owner_name.strip()
    if not owner_name:
        raise ValueError("Nome do proprietário vazio.")
    session = login(session)
    _, results = _pesquisar_fluxo(session, owner_name)
    return results


def abrir_detalhe_fluxo(
    owner_name: str,
    *,
    result_index: int | None = None,
    session: AspNetSession | None = None,
    comando: str = "fotos",
) -> tuple[AspNetSession, str, FluxoResult]:
    """Login → pesquisa → Ver Informações. Retorna (sessão, HTML do detalhe, resultado)."""
    owner_name = owner_name.strip()
    if not owner_name:
        raise ValueError("Nome do proprietário vazio.")

    session = login(session)
    html, results = _pesquisar_fluxo(session, owner_name)
    chosen = _pick_result(owner_name, results, result_index, comando=comando)

    logger.info('Abrindo "Ver Informações"...')
    fields = _fluxo_payload(
        html, owner_name, extra={chosen.button_name: "Ver Informações"}
    )
    parsed = parse_form_fields(html)
    for key in (
        "ctl00$body$droppagesize",
        "ctl00$body$txtpesquisagrid",
        "ctl00$body$hfTotalGrid",
    ):
        if key in parsed:
            fields[key] = parsed[key]
    html = session.post_html(FLUXO_PATH, fields)
    return session, html, chosen
