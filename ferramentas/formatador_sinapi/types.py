"""Tipos compartilhados do formatador."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Modelo(IntEnum):
    ATUALIZACAO = 1
    ENVIAR_PERITO = 2
    PARECER_INICIAL = 3

    @property
    def gera_word(self) -> bool:
        return self in (Modelo.ATUALIZACAO, Modelo.PARECER_INICIAL)

    @property
    def rotulo(self) -> str:
        return {
            Modelo.ATUALIZACAO: "Modelo 1 (Atualização)",
            Modelo.ENVIAR_PERITO: "Modelo 2 (Enviar ao Perito)",
            Modelo.PARECER_INICIAL: "Modelo 3 (Parecer Inicial)",
        }[self]


@dataclass
class ResultadoFormatacao:
    modelo: Modelo
    caminho_origem: str
    caminho_excel: str
    nome_obra: str
    referencia_sinapi: str = ""
    caminho_word: str | None = None
    avisos: list[str] = field(default_factory=list)
