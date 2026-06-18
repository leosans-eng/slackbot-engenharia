"""CLI local — Modelo 2 (Enviar ao Perito)."""

from formatador.cli import executar_formatacao_local, main
from formatador.types import Modelo


def ajustar_estetica_modelo2(caminho_origem_xlsx):
    """Compatível com chamadas anteriores; imprime no terminal e abre o Excel."""
    return executar_formatacao_local(Modelo.ENVIAR_PERITO, caminho_origem_xlsx)


if __name__ == "__main__":
    main(
        modelo_padrao=2,
        descricao="Formatador SINAPI — Modelo 2 (Enviar ao Perito)",
    )
