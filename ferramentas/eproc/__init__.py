"""Consulta somente leitura de processo judicial.

O número CNJ indica o tribunal. Hoje a consulta no site do tribunal
está ligada para a Justiça Federal da 2ª Região, no eproc.
Não peticiona, não movimenta e não altera cadastro.
"""

from ferramentas.eproc.leitura import ConsultaInterrompida

__all__ = ["ConsultaInterrompida"]
