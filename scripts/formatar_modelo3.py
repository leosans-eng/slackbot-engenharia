"""CLI local — formatar planilha SINAPI, Modelo 3 (Parecer Inicial)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ferramentas.formatador_sinapi.cli import executar_formatacao_local, main
from ferramentas.formatador_sinapi.types import Modelo


def ajustar_estetica_modelo3(caminho_origem_xlsx):
    """Compatível com chamadas anteriores; imprime no terminal e abre o Excel."""
    return executar_formatacao_local(Modelo.PARECER_INICIAL, caminho_origem_xlsx)


if __name__ == "__main__":
    main(
        modelo_padrao=3,
        descricao="slackbot-engenharia — formatar Modelo 3 (Parecer Inicial)",
    )
