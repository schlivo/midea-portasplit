"""Cache partagé : l'unique façon dont les autres outils voient/pilotent la
Midea, SANS jamais ouvrir de connexion vers elle (le poller en est le seul
propriétaire — la Midea ne tolère qu'une connexion à la fois).

- read_state()        -> dernier instantané (dict) écrit par le poller
- state_age()         -> ancienneté en secondes (None si pas de cache)
- queue_command(**kw) -> dépose un ordre que le poller appliquera au cycle suivant
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

_DIR = Path(__file__).parent
STATE_PATH = _DIR / "state.json"
CMD_PATH = _DIR / "command.json"


def _atomic_write(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj))
    os.replace(tmp, path)  # rename atomique : pas de lecture partielle


def write_state(state: dict) -> None:
    _atomic_write(STATE_PATH, state)


def read_state() -> Optional[dict]:
    if not STATE_PATH.exists():
        return None
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def state_age() -> Optional[float]:
    st = read_state()
    if not st or "ts_epoch" not in st:
        return None
    return time.time() - st["ts_epoch"]


def queue_command(**props) -> None:
    """Ex: queue_command(power=True, mode='COOL', target=18).
    Clés acceptées par le poller: power(bool), mode(str), target(float), fan(str)."""
    _atomic_write(CMD_PATH, props)


def pop_command() -> Optional[dict]:
    """Lu par le poller : renvoie l'ordre en attente et le supprime."""
    if not CMD_PATH.exists():
        return None
    try:
        cmd = json.loads(CMD_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        cmd = None
    try:
        CMD_PATH.unlink()
    except OSError:
        pass
    return cmd
