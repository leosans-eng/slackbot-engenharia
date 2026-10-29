"""Consulta somente leitura no eproc do TRF2.

Entra no processo, lê prazos e baixa laudo e despacho.
Não peticiona, não movimenta e não altera cadastro.
"""

from ferramentas.eproc.leitura import ConsultaInterrompida

__all__ = ["ConsultaInterrompida"]
