"""Seleção de data para o relatório de perícias finalizadas."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

# DD/MM, DD/MM/AA ou DD/MM/AAAA (também com - ou .)
_DATA_DIA_MES = re.compile(
    r"^(\d{1,2})[/\-.](\d{1,2})(?:[/\-.](\d{2}|\d{4}))?$"
)


def hoje() -> date:
    return date.today()


def ontem() -> date:
    return date.today() - timedelta(days=1)


def parse_data(text: str) -> date:
    """Aceita AAAA-MM-DD, DD/MM/AAAA, DD/MM (ano atual) e separadores - ou ."""
    text = text.strip()
    if not text:
        raise ValueError("Data vazia.")

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    match = _DATA_DIA_MES.fullmatch(text)
    if match:
        dia = int(match.group(1))
        mes = int(match.group(2))
        ano_txt = match.group(3)
        if ano_txt is None:
            ano = hoje().year
        elif len(ano_txt) == 2:
            ano = datetime.strptime(ano_txt, "%y").year
        else:
            ano = int(ano_txt)
        try:
            return date(ano, mes, dia)
        except ValueError:
            pass

    raise ValueError(
        f'Data inválida: "{text}". Use AAAA-MM-DD (ex.: 2026-07-28), '
        "DD/MM/AAAA ou DD/MM (ano atual)."
    )
