"""Cache em memória da última planilha enviada por usuário/canal."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ArquivoPendente:
    file_id: str
    nome: str


# (user_id, channel_id) → última planilha .xlsx recebida
_planilhas_pendentes: dict[tuple[str, str], ArquivoPendente] = {}


def registrar_planilha(user_id: str, channel_id: str, file_id: str, nome: str) -> None:
    _planilhas_pendentes[(user_id, channel_id)] = ArquivoPendente(
        file_id=file_id,
        nome=nome,
    )


def obter_planilha_pendente(user_id: str, channel_id: str) -> ArquivoPendente | None:
    return _planilhas_pendentes.get((user_id, channel_id))


def remover_planilha_pendente(user_id: str, channel_id: str) -> None:
    _planilhas_pendentes.pop((user_id, channel_id), None)
