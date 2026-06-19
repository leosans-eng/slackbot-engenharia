"""Ponto de entrada unificado para formatação de planilhas."""

from __future__ import annotations

from ferramentas.formatador_sinapi.modelo1 import formatar_modelo1
from ferramentas.formatador_sinapi.modelo2 import formatar_modelo2
from ferramentas.formatador_sinapi.modelo3 import formatar_modelo3
from ferramentas.formatador_sinapi.types import Modelo, ResultadoFormatacao

_FORMATADORES = {
    Modelo.ATUALIZACAO: formatar_modelo1,
    Modelo.ENVIAR_PERITO: formatar_modelo2,
    Modelo.PARECER_INICIAL: formatar_modelo3,
}


def _gerar_word(resultado: ResultadoFormatacao) -> str | None:
    if resultado.modelo == Modelo.ATUALIZACAO:
        from ferramentas.formatador_sinapi.word_modelo1 import gerar_word_modelo1

        return gerar_word_modelo1(resultado.caminho_excel, abrir_arquivo=False)
    if resultado.modelo == Modelo.PARECER_INICIAL:
        from ferramentas.formatador_sinapi.word_modelo3 import gerar_word_modelo3

        return gerar_word_modelo3(resultado.caminho_excel, abrir_arquivo=False)
    return None


def formatar_planilha(
    caminho_origem: str,
    modelo: Modelo | int = Modelo.ATUALIZACAO,
    *,
    caminho_saida: str | None = None,
    diretorio_saida: str | None = None,
    gerar_word: bool | None = None,
) -> ResultadoFormatacao:
    """
    Formata uma planilha SINAPI no modelo indicado.

    Parâmetros opcionais de saída permitem uso em bot/servidor com diretório temporário.
    """
    modelo_enum = Modelo(modelo)
    formatador = _FORMATADORES[modelo_enum]
    resultado = formatador(
        caminho_origem,
        caminho_saida=caminho_saida,
        diretorio_saida=diretorio_saida,
    )

    deve_gerar_word = modelo_enum.gera_word if gerar_word is None else gerar_word
    if deve_gerar_word:
        try:
            resultado.caminho_word = _gerar_word(resultado)
        except Exception as erro:
            resultado.avisos.append(f"Word não gerado: {erro}")

    return resultado
