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
            "Configure LOGIN_USER e LOGIN_PASS (e opcionalmente BASE_URL) no `.env`."
        )
    return value


BASE_URL = os.getenv("BASE_URL", "http://andreserver:5050").rstrip("/")
LOGIN_URL = f"{BASE_URL}/Login"
FLUXO_URL = f"{BASE_URL}/FluxoTrabalho/ControleFluxoTrabalho"
PERICIA_FINALIZADA_URL = f"{BASE_URL}/PericiaJudicial/PericiaFinalizada"

LOGIN_USER = os.getenv("LOGIN_USER", "").strip()
LOGIN_PASS = os.getenv("LOGIN_PASS", "").strip()


def require_credentials() -> tuple[str, str]:
    """Retorna (user, pass) ou levanta ValueError com mensagem clara."""
    user = LOGIN_USER or _require("LOGIN_USER")
    password = LOGIN_PASS or _require("LOGIN_PASS")
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
