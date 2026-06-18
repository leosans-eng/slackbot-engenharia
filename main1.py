"""CLI local — Modelo 1 (Atualização)."""

from formatador.cli import executar_formatacao_local, main
from formatador.types import Modelo


def ajustar_estetica_modelo1(caminho_origem_xlsx):
    """Compatível com chamadas anteriores; imprime no terminal e abre o Excel."""
    return executar_formatacao_local(Modelo.ATUALIZACAO, caminho_origem_xlsx)


if __name__ == "__main__":
    main(
        modelo_padrao=1,
        descricao="Formatador SINAPI — Modelo 1 (Atualização)",
    )
