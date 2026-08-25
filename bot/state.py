"""Cache em memória da última planilha enviada e da prévia de revisão."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass(frozen=True)
class ArquivoPendente:
    file_id: str
    nome: str


@dataclass(frozen=True)
class RevisaoPendente:
    criado_em: datetime


# (user_id, channel_id) → última planilha .xlsx recebida
_planilhas_pendentes: dict[tuple[str, str], ArquivoPendente] = {}

# (user_id, channel_id) → prévia de /revisao aguardando "sim"
_revisoes_pendentes: dict[tuple[str, str], RevisaoPendente] = {}
EXPIRACAO_REVISAO = timedelta(hours=2)


def registrar_planilha(user_id: str, channel_id: str, file_id: str, nome: str) -> None:
    _planilhas_pendentes[(user_id, channel_id)] = ArquivoPendente(
        file_id=file_id,
        nome=nome,
    )


def obter_planilha_pendente(user_id: str, channel_id: str) -> ArquivoPendente | None:
    return _planilhas_pendentes.get((user_id, channel_id))


def remover_planilha_pendente(user_id: str, channel_id: str) -> None:
    _planilhas_pendentes.pop((user_id, channel_id), None)


def registrar_revisao_pendente(user_id: str, channel_id: str) -> None:
    _revisoes_pendentes[(user_id, channel_id)] = RevisaoPendente(
        criado_em=datetime.now()
    )


def obter_revisao_pendente(user_id: str, channel_id: str) -> RevisaoPendente | None:
    chave = (user_id, channel_id)
    pendente = _revisoes_pendentes.get(chave)
    if pendente is None:
        return None
    if datetime.now() - pendente.criado_em > EXPIRACAO_REVISAO:
        _revisoes_pendentes.pop(chave, None)
        return None
    return pendente


def remover_revisao_pendente(user_id: str, channel_id: str) -> None:
    _revisoes_pendentes.pop((user_id, channel_id), None)
