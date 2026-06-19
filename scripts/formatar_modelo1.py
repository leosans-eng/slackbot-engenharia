"""CLI local — formatar planilha SINAPI, Modelo 1 (Atualização)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ferramentas.formatador_sinapi.cli import executar_formatacao_local, main
from ferramentas.formatador_sinapi.types import Modelo


def ajustar_estetica_modelo1(caminho_origem_xlsx):
    """Compatível com chamadas anteriores; imprime no terminal e abre o Excel."""
    return executar_formatacao_local(Modelo.ATUALIZACAO, caminho_origem_xlsx)


if __name__ == "__main__":
    main(
        modelo_padrao=1,
        descricao="slackbot-engenharia — formatar Modelo 1 (Atualização)",
    )
