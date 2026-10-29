"""Download de Excel de Perícia Finalizada via HTTP (sem Playwright)."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from ferramentas.idebras.aspnet import AspNetSession, login, parse_hidden_fields
from ferramentas.idebras.config import PERICIA_FINALIZADA_URL, pericias_output_dir
from ferramentas.idebras.formatar_pericias import formatar_pericias_finalizadas
from ferramentas.idebras.pericias_datas import hoje

logger = logging.getLogger(__name__)

TEMP_XLSX = re.compile(r"/Temp/[0-9a-fA-F\-]+\.xlsx")
PATH = "/PericiaJudicial/PericiaFinalizada"
HF_TOTAL = re.compile(
    r'name=["\']ctl00\$body\$hfTotalGrid["\'][^>]*value=["\'](\d+)["\']'
    r"|value=[\"'](\d+)[\"'][^>]*name=[\"']ctl00\$body\$hfTotalGrid[\"']",
    re.I,
)
MSG_VAZIO = re.compile(
    r"nenhum\s+registro|n[aã]o\s+(h[aá]|existem?)\s+registro|sem\s+registros|"
    r"nenhuma\s+per[ií]cia|0\s+registro",
    re.I,
)


class SemPericiasError(Exception):
    """Nenhuma perícia finalizada na data solicitada."""

    def __init__(self, day: date) -> None:
        self.day = day
        super().__init__(
            f"Nenhuma perícia finalizada em *{day.strftime('%d/%m/%Y')}*."
        )


def pericias_excel_path(output_dir: Path, day: date) -> Path:
    return output_dir / f"pericias_finalizadas_{day.isoformat()}.xlsx"


def gerar_relatorio_pericias(
    day: date | None = None,
    *,
    output_dir: Path | None = None,
    session: AspNetSession | None = None,
) -> Path:
    """Gera o Excel formatado para a data informada (padrão: hoje).

    Raises:
        SemPericiasError: se a pesquisa não retornar registros.
    """
    day = day or hoje()
    out_dir = output_dir or pericias_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    excel_path = pericias_excel_path(out_dir, day)
    return download_pericias_excel(excel_path, day=day, session=session)


def _search_fields(day: date, base: dict[str, str] | None = None) -> dict[str, str]:
    iso = day.isoformat()
    fields = dict(base or {})
    fields.update(
        {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$body$dropconjuntopesquisa": "TODOS",
            "ctl00$body$dropperitopesquisa": "TODOS",
            "ctl00$body$dpinicio": "",
            "ctl00$body$dpfinal": "",
            "ctl00$body$dpiniciofinalizada": iso,
            "ctl00$body$dpfinalfinalizada": iso,
            "ctl00$body$dropcomarcapesquisa": "TODAS",
            "ctl00$body$dropufpesquisa": "SELECIONE",
            "ctl00$body$txtnomeclientepesquisa": "",
            "ctl00$body$btnpesquisarfluxo": "Pesquisar",
            "ctl00$body$dropetapaservico": "SELECIONE",
            "ctl00$body$dropfuncionario": "SELECIONE",
            "ctl00$body$txtobservacaofinal": "",
        }
    )
    return fields


def _excel_fields(day: date, base: dict[str, str]) -> dict[str, str]:
    iso = day.isoformat()
    fields = dict(base)
    fields.update(
        {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$body$dropconjuntopesquisa": "TODOS",
            "ctl00$body$dropperitopesquisa": "TODOS",
            "ctl00$body$dpinicio": "",
            "ctl00$body$dpfinal": "",
            "ctl00$body$dpiniciofinalizada": iso,
            "ctl00$body$dpfinalfinalizada": iso,
            "ctl00$body$dropcomarcapesquisa": "TODAS",
            "ctl00$body$dropufpesquisa": "SELECIONE",
            "ctl00$body$txtnomeclientepesquisa": "",
            "ctl00$body$btnexportarexcel": "Excel",
            "ctl00$body$droppagesize": fields.get("ctl00$body$droppagesize", "10"),
            "ctl00$body$txtpesquisagrid": "",
            "ctl00$body$dropetapaservico": "SELECIONE",
            "ctl00$body$dropfuncionario": "SELECIONE",
            "ctl00$body$txtobservacaofinal": "",
        }
    )
    fields.pop("ctl00$body$btnpesquisarfluxo", None)
    return fields


def _pesquisa_sem_resultados(html: str) -> bool:
    """Heurística: grid vazio / mensagem de nenhum registro."""
    m = HF_TOTAL.search(html)
    if m:
        total = int(m.group(1) or m.group(2) or "0")
        if total == 0:
            return True
    if MSG_VAZIO.search(html):
        return True
    return False


class NomeSemPericiaError(Exception):
    """Nenhuma perícia finalizada para o nome informado."""

    def __init__(self, nome: str) -> None:
        self.nome = nome
        super().__init__(f"Não achei perícia finalizada de {nome} no Idebras.")


@dataclass(frozen=True)
class ProcessoPericia:
    numero: str
    autor: str
    vara: str
    comarca: str


def buscar_processos_finalizados(nome: str, *, session: AspNetSession | None = None) -> list[ProcessoPericia]:
    """Perícias finalizadas desse nome, um registro por número de processo."""
    consulta = " ".join((nome or "").split())
    if not consulta:
        raise ValueError("Informe o nome para pesquisar no Idebras.")
    session = login(session)
    logger.info("Abrindo Perícia Finalizada para pesquisa por nome...")
    html = session.get_html(PATH)
    if not re.search(r"data\s*finalizada", html, re.I):
        raise RuntimeError(
            f"Página inesperada em {PERICIA_FINALIZADA_URL}. "
            "Login pode ter expirado ou a URL mudou."
        )
    html = session.post_html(
        PATH, _campos_nome(consulta, parse_hidden_fields(html), exportar=False)
    )
    if _pesquisa_sem_resultados(html):
        raise NomeSemPericiaError(consulta)

    try:
        html = session.post_html(
            PATH, _campos_nome(consulta, parse_hidden_fields(html), exportar=True)
        )
    except RuntimeError as exc:
        if "HTTP 500" in str(exc):
            raise NomeSemPericiaError(consulta) from exc
        raise
    match = TEMP_XLSX.search(html)
    if not match:
        raise NomeSemPericiaError(consulta)

    _, data, ctype = session.get(match.group(0))
    if data[:2] != b"PK" and "sheet" not in ctype.lower() and "octet" not in ctype.lower():
        raise RuntimeError("O Idebras não devolveu a planilha das perícias.")

    pasta = pericias_output_dir() / "busca-nome"
    pasta.mkdir(parents=True, exist_ok=True)
    bruto = pasta / "pericias_nome_bruto.xlsx"
    bruto.write_bytes(data)
    from ferramentas.idebras.formatar_pericias import listar_processos_brutos

    achados = _unicos_por_processo(listar_processos_brutos(bruto), consulta)
    if not achados:
        raise NomeSemPericiaError(consulta)
    return achados


def _campos_nome(nome: str, base: dict[str, str], *, exportar: bool) -> dict[str, str]:
    fields = dict(base)
    fields.update(
        {
            "__EVENTTARGET": "",
            "__EVENTARGUMENT": "",
            "ctl00$body$dropconjuntopesquisa": "TODOS",
            "ctl00$body$dropperitopesquisa": "TODOS",
            "ctl00$body$dpinicio": "",
            "ctl00$body$dpfinal": "",
            "ctl00$body$dpiniciofinalizada": "",
            "ctl00$body$dpfinalfinalizada": "",
            "ctl00$body$dropcomarcapesquisa": "TODAS",
            "ctl00$body$dropufpesquisa": "SELECIONE",
            "ctl00$body$txtnomeclientepesquisa": nome,
            "ctl00$body$dropetapaservico": "SELECIONE",
            "ctl00$body$dropfuncionario": "SELECIONE",
            "ctl00$body$txtobservacaofinal": "",
        }
    )
    if exportar:
        fields["ctl00$body$btnexportarexcel"] = "Excel"
        fields.pop("ctl00$body$btnpesquisarfluxo", None)
        fields["ctl00$body$droppagesize"] = fields.get("ctl00$body$droppagesize", "10")
        fields["ctl00$body$txtpesquisagrid"] = ""
    else:
        fields["ctl00$body$btnpesquisarfluxo"] = "Pesquisar"
        fields.pop("ctl00$body$btnexportarexcel", None)
    return fields


def _unicos_por_processo(linhas: list[dict[str, str]], nome: str) -> list[ProcessoPericia]:
    palavras = [
        p
        for p in re.findall(r"[a-z0-9]+", _sem_acento(nome).casefold())
        if p not in _IGNORAR_BUSCA
    ]
    escolhidas = []
    for linha in linhas:
        autor = _sem_acento(linha.get("autor", "")).casefold()
        if palavras and not all(palavra in autor for palavra in palavras):
            continue
        numero = _cnj(linha.get("processo", ""))
        if numero:
            escolhidas.append((numero, linha))
    vistos: dict[str, ProcessoPericia] = {}
    for numero, linha in escolhidas:
        if numero in vistos:
            continue
        vistos[numero] = ProcessoPericia(
            numero=numero,
            autor=linha.get("autor", ""),
            vara=linha.get("vara", ""),
            comarca=linha.get("comarca", ""),
        )
    return list(vistos.values())


def _cnj(texto: str) -> str | None:
    match = re.search(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}", texto or "")
    if match:
        return match.group(0)
    digitos = re.sub(r"\D", "", texto or "")
    if len(digitos) != 20:
        return None
    return (
        f"{digitos[0:7]}-{digitos[7:9]}.{digitos[9:13]}."
        f"{digitos[13]}.{digitos[14:16]}.{digitos[16:20]}"
    )


def _sem_acento(texto: str) -> str:
    return (texto or "").translate(
        str.maketrans(
            "áàâãéêíóôõúçÁÀÂÃÉÊÍÓÔÕÚÇ",
            "aaaaeeioooucAAAAEEIOOOUC",
        )
    )


_IGNORAR_BUSCA = {
    "de", "da", "do", "das", "dos", "e", "o", "a", "os", "as",
    "na", "no", "nos", "nas", "em",
}


def download_pericias_excel(
    excel_path: Path,
    *,
    day: date | None = None,
    session: AspNetSession | None = None,
) -> Path:
    """Login → PericiaFinalizada → Data Finalizada=day → Pesquisar → Excel → /Temp/*.xlsx."""
    day = day or hoje()
    session = login(session)

    logger.info("Abrindo Perícia Finalizada...")
    html = session.get_html(PATH)
    if not re.search(r"data\s*finalizada", html, re.I):
        raise RuntimeError(
            f"Página inesperada em {PERICIA_FINALIZADA_URL}. "
            "Login pode ter expirado ou a URL mudou."
        )

    logger.info("Pesquisando Data Finalizada = %s...", day.strftime("%d/%m/%Y"))
    html = session.post_html(PATH, _search_fields(day, parse_hidden_fields(html)))

    if _pesquisa_sem_resultados(html):
        logger.info("Nenhuma perícia finalizada em %s.", day.isoformat())
        raise SemPericiasError(day)

    logger.info("Exportando Excel...")
    try:
        html = session.post_html(PATH, _excel_fields(day, parse_hidden_fields(html)))
    except RuntimeError as exc:
        # O servidor costuma responder HTTP 500 ao exportar com zero linhas
        if "HTTP 500" in str(exc):
            logger.info(
                "Export Excel retornou HTTP 500 — tratando como sem perícias em %s.",
                day.isoformat(),
            )
            raise SemPericiasError(day) from exc
        raise

    match = TEMP_XLSX.search(html)
    if not match:
        logger.info(
            "Export sem link /Temp/*.xlsx — tratando como sem perícias em %s.",
            day.isoformat(),
        )
        raise SemPericiasError(day)

    temp_path = match.group(0)
    logger.info("Baixando %s...", temp_path)
    _, data, ctype = session.get(temp_path)
    if data[:2] != b"PK" and "sheet" not in ctype.lower() and "octet" not in ctype.lower():
        raise RuntimeError(
            f"Download de {temp_path} não parece Excel (Content-Type={ctype!r})."
        )

    excel_path = Path(excel_path)
    if excel_path.suffix.lower() not in {".xls", ".xlsx"}:
        excel_path = excel_path.with_suffix(".xlsx")
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    raw_path = excel_path.with_name(excel_path.stem + "_bruto.xlsx")
    raw_path.write_bytes(data)
    logger.info("Excel bruto salvo em: %s", raw_path)

    logger.info("Formatando relatório...")
    formatar_pericias_finalizadas(raw_path, excel_path)
    logger.info("Excel formatado em: %s", excel_path)
    return excel_path
