"""Seleção de data para o relatório de perícias finalizadas."""

from __future__ import annotations

from datetime import date, datetime, timedelta


def hoje() -> date:
    return date.today()


def ontem() -> date:
    return date.today() - timedelta(days=1)


def parse_data(text: str) -> date:
    """Aceita AAAA-MM-DD ou DD/MM/AAAA."""
    text = text.strip()
    if not text:
        raise ValueError("Data vazia.")

    try:
        return date.fromisoformat(text)
    except ValueError:
        pass

    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue

    raise ValueError(
        f'Data inválida: "{text}". Use AAAA-MM-DD (ex.: 2026-07-28) ou DD/MM/AAAA.'
    )
