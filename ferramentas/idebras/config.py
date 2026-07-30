"""Configuração do Idebras (variáveis de ambiente)."""

from __future__ import annotations

import os
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = ROOT_DIR / "tmp" / "idebras"


def _require(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise ValueError(
            f"Variável de ambiente `{name}` não definida. "
            "Configure no `.env`."
        )
    return value


# --- Idebras (HTTP) ---
BASE_URL = os.getenv("BASE_URL", "http://andreserver:5050").rstrip("/")
LOGIN_URL = f"{BASE_URL}/Login"
FLUXO_URL = f"{BASE_URL}/FluxoTrabalho/ControleFluxoTrabalho"
PERICIA_FINALIZADA_URL = f"{BASE_URL}/PericiaJudicial/PericiaFinalizada"

LOGIN_USER = os.getenv("LOGIN_USER", "").strip()
LOGIN_PASS = os.getenv("LOGIN_PASS", "").strip()

# --- CP Infobase (desktop UI) ---
CP_USER = os.getenv("CP_USER", "").strip()
CP_PASS = os.getenv("CP_PASS", "").strip()
CP_EXE = Path(
    os.getenv(
        "CP_EXE",
        r"C:\Program Files (x86)\Advocacia Valera\CP MCMV\infobase.exe",
    )
)

# Canal/usuário fixo para envio automático dos fluxos CP
FLUXOS_CP_CANAL = os.getenv("FLUXOS_CP_CANAL", "").strip()
# Horário diário no formato HH:MM (ex.: "08:00")
FLUXOS_CP_HORARIO = os.getenv("FLUXOS_CP_HORARIO", "").strip()

# Canal/usuário fixo para envio automático de perícias finalizadas
PERICIAS_CANAL = os.getenv("PERICIAS_CANAL", "").strip()
PERICIAS_HORARIO = os.getenv("PERICIAS_HORARIO", "").strip()


def require_credentials() -> tuple[str, str]:
    """Retorna (user, pass) do Idebras ou levanta ValueError."""
    user = LOGIN_USER or _require("LOGIN_USER")
    password = LOGIN_PASS or _require("LOGIN_PASS")
    return user, password


def require_cp_credentials() -> tuple[str, str]:
    """Retorna (user, pass) do Infobase CP ou levanta ValueError."""
    user = CP_USER or _require("CP_USER")
    password = CP_PASS or _require("CP_PASS")
    return user, password


def owner_output_dir(owner_name: str, base: Path | None = None) -> Path:
    """Pasta de saída segura para o nome do proprietário."""
    safe = "".join(c if c.isalnum() or c in " -_" else "_" for c in owner_name)
    safe = " ".join(safe.split()).strip() or "proprietario"
    path = (base or OUTPUT_DIR) / safe
    path.mkdir(parents=True, exist_ok=True)
    return path


def pericias_output_dir(base: Path | None = None) -> Path:
    path = (base or OUTPUT_DIR) / "pericias"
    path.mkdir(parents=True, exist_ok=True)
    return path


def fluxos_cp_output_dir(base: Path | None = None) -> Path:
    path = (base or OUTPUT_DIR) / "fluxos-cp"
    path.mkdir(parents=True, exist_ok=True)
    return path
