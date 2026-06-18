"""CLI local para execução dos modelos (uso em desktop)."""

from __future__ import annotations

import argparse

from formatador.entrada import ArquivoEntradaAmbiguo, resolver_arquivo_entrada
from formatador.service import formatar_planilha
from formatador.sistema import abrir_arquivo
from formatador.types import Modelo


def _imprimir_sucesso(resultado) -> None:
    print(
        f"\n🟢 Sucesso! Planilha gerada no formato do {resultado.modelo.rotulo}: "
        f"'{resultado.caminho_excel}'\n"
    )
    if resultado.caminho_word:
        print(f"🟢 Documento Word gerado: '{resultado.caminho_word}'\n")
    for aviso in resultado.avisos:
        print(f"⚠️ {aviso}\n")


def _imprimir_erro_arquivo(caminho: str) -> None:
    print(f"\n🔴 ERRO: O arquivo '{caminho}' não foi encontrado.")
    print("Informe o caminho na linha de comando ou configure local_config.py.\n")


def _imprimir_erro_entrada(erro: Exception) -> None:
    print(f"\n🔴 ERRO: {erro}\n")


def executar_formatacao_local(
    modelo: Modelo | int,
    caminho_origem: str,
    *,
    abrir_resultado: bool = True,
    gerar_word: bool | None = None,
):
    """Executa a formatação com feedback no terminal e abertura do arquivo."""
    try:
        resultado = formatar_planilha(
            caminho_origem,
            modelo=modelo,
            gerar_word=gerar_word,
        )
    except FileNotFoundError:
        _imprimir_erro_arquivo(caminho_origem)
        return None

    _imprimir_sucesso(resultado)
    if abrir_resultado:
        abrir_arquivo(resultado.caminho_excel)
    return resultado


def criar_parser(descricao: str, modelo_padrao: int) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=descricao)
    parser.add_argument(
        "arquivo",
        nargs="?",
        default=None,
        help=(
            "Planilha de origem (.xlsx). Se omitido, usa local_config.py, "
            "FORMATADOR_ARQUIVO_ENTRADA ou detecção automática na pasta."
        ),
    )
    parser.add_argument(
        "--modelo",
        type=int,
        choices=[1, 2, 3],
        default=modelo_padrao,
        help="Modelo de formatação (1, 2 ou 3)",
    )
    parser.add_argument(
        "--sem-abrir",
        action="store_true",
        help="Não abre o arquivo gerado automaticamente",
    )
    parser.add_argument(
        "--sem-word",
        action="store_true",
        help="Não gera documento Word (modelos 1 e 3)",
    )
    return parser


def main(modelo_padrao: int, descricao: str) -> None:
    parser = criar_parser(descricao, modelo_padrao)
    args = parser.parse_args()

    try:
        caminho_origem, origem = resolver_arquivo_entrada(args.arquivo)
    except (FileNotFoundError, ArquivoEntradaAmbiguo) as erro:
        _imprimir_erro_entrada(erro)
        return

    if origem != "informado na linha de comando":
        print(f"📄 Entrada ({origem}): '{caminho_origem}'\n")

    gerar_word = False if args.sem_word else None
    executar_formatacao_local(
        args.modelo,
        caminho_origem,
        abrir_resultado=not args.sem_abrir,
        gerar_word=gerar_word,
    )
