"""CLI local — Modelo 3 (Parecer Inicial)."""

from formatador.cli import executar_formatacao_local, main
from formatador.types import Modelo


def ajustar_estetica_modelo3(caminho_origem_xlsx):
    """Compatível com chamadas anteriores; imprime no terminal e abre o Excel."""
    return executar_formatacao_local(Modelo.PARECER_INICIAL, caminho_origem_xlsx)


if __name__ == "__main__":
    main(
        modelo_padrao=3,
        descricao="Formatador SINAPI — Modelo 3 (Parecer Inicial)",
    )
