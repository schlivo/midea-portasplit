"""Chargement de la config depuis .env (aucun secret en dur dans le code).

Tous les modules importent leurs identifiants d'ici. Le .env est gitignoré ;
voir .env.example pour le format.
"""
from __future__ import annotations

from pathlib import Path

ENV_PATH = Path(__file__).with_name(".env")


def load_env() -> dict:
    env = {}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def get(key: str, default=None, cast=str):
    v = load_env().get(key, default)
    if v is None or v == "":
        return default
    try:
        return cast(v)
    except (ValueError, TypeError):
        return default
