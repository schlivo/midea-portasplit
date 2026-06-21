"""Thermostat — consommateur du cache (ne touche JAMAIS la Midea directement).

Lit le dernier état publié par le poller (state.json), décide via la même
logique que le poller, puis :
  - dry-run (défaut) : affiche la décision
  - --apply          : dépose l'ordre dans la file (command.json) ; c'est le
                       poller, seul propriétaire de la connexion, qui l'exécute.

Le vrai pilotage intégré reste `poller.py --control --apply`. Cet outil sert
à régler/expérimenter target & deadband en parallèle, sans collision.
"""
from __future__ import annotations

import argparse
import time
from dataclasses import fields

import aclib
import cache
from poller import regulate


def _state_obj(state: dict) -> aclib.State:
    allowed = {f.name for f in fields(aclib.State)}
    return aclib.State(**{k: v for k, v in state.items() if k in allowed})


def step(target: float, deadband: float, apply: bool, max_age: float = 300) -> str:
    state = cache.read_state()
    if not state:
        return "pas de cache (le poller tourne-t-il ?)"
    age = cache.state_age()
    if age is not None and age > max_age:
        return f"cache périmé ({int(age)}s) — le poller est-il arrêté ?"

    room = state.get("netatmo_temp")
    st = _state_obj(state)
    action, props = regulate(room, st, target, deadband)
    base = f"pièce {room}°C | cible {target}±{deadband}°C | clim {st.mode} {st.power_w}W"
    if props is None:
        return f"{base}  -> {action}"
    if apply:
        cache.queue_command(**props)
        return f"{base}  -> {action}  ✓ (ordre déposé pour le poller)"
    return f"{base}  -> {action}  [DRY-RUN]"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", type=float, required=True)
    p.add_argument("--deadband", type=float, default=0.4)
    p.add_argument("--interval", type=int, default=180)
    p.add_argument("--once", action="store_true")
    p.add_argument("--apply", action="store_true")
    args = p.parse_args()

    print(f"# Thermostat (cache) cible {args.target}°C "
          f"{'APPLY (via file)' if args.apply else 'DRY-RUN'}", flush=True)
    while True:
        print(time.strftime("%H:%M:%S") + "  " +
              step(args.target, args.deadband, args.apply), flush=True)
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
