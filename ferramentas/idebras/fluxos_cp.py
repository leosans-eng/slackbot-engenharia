"""Export + formatação dos fluxos do CP (Infobase MCMV).

Para uso automatizado (Slack), o bot abre o Infobase via UI na mesma máquina.
Também aceita from_xlsx= para formatar um Excel já exportado.
"""

from __future__ import annotations

import logging
import shutil
from datetime import date
from pathlib import Path

from ferramentas.idebras.config import fluxos_cp_output_dir
from ferramentas.idebras.formatar_fluxos_cp import formatar_fluxos_cp

logger = logging.getLogger(__name__)


def fluxos_cp_excel_path(output_dir: Path, day: date | None = None) -> Path:
    day = day or date.today()
    return output_dir / f"fluxos_cp_{day.isoformat()}.xlsx"


def download_fluxos_cp_excel(
    excel_path: Path,
    *,
    from_xlsx: Path | None = None,
    close_app: bool = False,
) -> Path:
    """Obtém o Excel bruto e salva em excel_path."""
    excel_path = Path(excel_path)
    if excel_path.suffix.lower() != ".xlsx":
        excel_path = excel_path.with_suffix(".xlsx")
    excel_path.parent.mkdir(parents=True, exist_ok=True)

    if from_xlsx is not None:
        src = Path(from_xlsx)
        if not src.is_file():
            raise FileNotFoundError(f"Arquivo não encontrado: {src}")
        shutil.copy2(src, excel_path)
        logger.info("Excel bruto (from_xlsx): %s", excel_path)
        return excel_path

    from ferramentas.idebras.fluxos_cp_ui import export_fluxos_via_ui

    exported = export_fluxos_via_ui(close_app=close_app)
    shutil.copy2(exported, excel_path)
    logger.info("Excel bruto (UI): %s", excel_path)
    return excel_path


def gerar_relatorio_fluxos_cp(
    *,
    output_dir: Path | None = None,
    from_xlsx: Path | None = None,
    day: date | None = None,
    close_app: bool = False,
) -> Path:
    """Captura (ou from_xlsx) + formata no padrão do modelo.

    Retorna o path do Excel formatado.
    """
    out_dir = output_dir or fluxos_cp_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    day = day or date.today()
    final_path = fluxos_cp_excel_path(out_dir, day)
    raw_path = final_path.with_name(final_path.stem + "_bruto.xlsx")

    download_fluxos_cp_excel(raw_path, from_xlsx=from_xlsx, close_app=close_app)
    logger.info("Formatando fluxos CP...")
    formatar_fluxos_cp(raw_path, final_path)
    logger.info("Relatório pronto: %s", final_path)
    return final_path
