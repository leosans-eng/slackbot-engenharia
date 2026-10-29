"""Resumo curto de prazos para a mensagem que acompanha a planilha no Slack."""

from __future__ import annotations

from datetime import date, timedelta

_LIMITE_NOMES = 12


def mensagem_pericias(
    dia: date,
    itens: list[tuple[str, date | None]],
    *,
    hoje: date | None = None,
) -> str:
    """Laudos do dia e prazos de peticionamento vencidos, de hoje e de amanhã."""
    referencia = hoje or date.today()
    linhas = [
        f"Perícias finalizadas — *{dia.strftime('%d/%m/%Y')}*",
        _contagem(len(itens), "laudo", "laudos") + ".",
        "",
    ]
    linhas.extend(
        _bloco("Prazo de peticionamento", itens, referencia)
    )
    return "\n".join(linhas).strip()


def _contagem(n: int, um: str, varios: str) -> str:
    return f"*{n}* {um if n == 1 else varios}"


def _bloco(
    titulo: str,
    itens: list[tuple[str, date | None]],
    hoje: date,
) -> list[str]:
    datados = [(nome, prazo) for nome, prazo in itens if prazo is not None]
    grupos = _agrupar(datados, hoje)
    linhas = [f"*{titulo}*"]
    for chave, rotulo, com_data in (
        ("vencidos", "Vencidos", True),
        ("hoje", "Hoje", False),
        ("amanha", "Amanhã", False),
    ):
        linha = _linha_nomes(rotulo, grupos[chave], com_data=com_data)
        if linha:
            linhas.append(linha)
    if len(linhas) == 1:
        linhas.append("Nenhum vence hoje ou amanhã, e não há prazo vencido.")
    return linhas


def _agrupar(
    itens: list[tuple[str, date]],
    hoje: date,
) -> dict[str, list[tuple[str, date]]]:
    grupos: dict[str, list[tuple[str, date]]] = {
        "vencidos": [],
        "hoje": [],
        "amanha": [],
    }
    amanha = hoje + timedelta(days=1)
    for nome, prazo in itens:
        if prazo < hoje:
            grupos["vencidos"].append((nome, prazo))
        elif prazo == hoje:
            grupos["hoje"].append((nome, prazo))
        elif prazo == amanha:
            grupos["amanha"].append((nome, prazo))
    grupos["vencidos"].sort(key=lambda item: (item[1], item[0].casefold()))
    grupos["hoje"].sort(key=lambda item: item[0].casefold())
    grupos["amanha"].sort(key=lambda item: item[0].casefold())
    return grupos


def _linha_nomes(
    rotulo: str,
    itens: list[tuple[str, date]],
    *,
    com_data: bool,
) -> str:
    if not itens:
        return ""
    partes: list[str] = []
    for nome, prazo in itens[:_LIMITE_NOMES]:
        if com_data:
            partes.append(f"{nome} ({prazo.strftime('%d/%m')})")
        else:
            partes.append(nome)
    texto = ", ".join(partes)
    resto = len(itens) - _LIMITE_NOMES
    if resto > 0:
        texto += f" e mais {resto}"
    return f"• *{rotulo}* ({len(itens)}): {texto}"
