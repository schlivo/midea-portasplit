"""Poller central — SEUL propriétaire de la connexion Midea.

Chaque cycle :
  1. applique l'ordre en attente (cache.command.json) s'il y en a un
  2. lit la Midea (avec conso) + le Netatmo
  3. publie l'instantané dans state.json  (lu par tous les autres outils)
  4. ajoute une ligne au CSV d'historique
  5. (option --control) régule la pièce sur la sonde Netatmo

Comme tout passe par ce processus unique, plus aucune collision sur la Midea.

Usage:
  uv run python poller.py                              # poll + log + cache
  uv run python poller.py --control --target 25        # + régulation DRY-RUN
  uv run python poller.py --control --target 25 --apply  # + régulation réelle
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

import aclib
import cache
import netatmo
import weather

CSV_PATH = Path(__file__).with_name("climate_log.csv")
FIELDS = ["timestamp", "netatmo_temp", "midea_temp", "outdoor_temp",
          "ac_power", "ac_mode", "ac_setpoint", "power_w", "energy_kwh",
          "netatmo_setpoint", "netatmo_mode", "heating",
          "ambient_temp", "heat_delta"]
COOL_HARD_SETPOINT = 18.0


def append_csv(row: dict) -> None:
    new = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="") as f:
        w = csv.DictWriter(f, fieldnames={k: None for k in FIELDS})
        if new:
            w.writeheader()
        w.writerow({k: row.get(k) for k in FIELDS})


def regulate(room, st, target, deadband):
    """Renvoie (action_str, props|None) sans rien appliquer.

    La consigne Midea est bloquée à 24°C (plancher) et turbo ne répond pas, donc
    on module l'INTENSITÉ via les leviers qui marchent : power on/off, eco off,
    ventilo MAX. On réaffirme la config froide à chaque cycle (lectures eco/power
    peu fiables -> commande idempotente). On juge l'état via power_w."""
    running = st.power_w is not None and st.power_w > 30
    if room is None:
        return "pas de mesure pièce", None
    if room >= target + deadband:
        # froid à fond : consigne basse (range élargi à 18°C) + eco off + ventilo MAX.
        # C'est notre boucle Netatmo qui coupe à la vraie cible, pas la sonde Midea.
        return "FROID MAX (consigne 18, eco off, ventilo MAX)", dict(
            power=True, mode="COOL", eco=False, fan="MAX", target=COOL_HARD_SETPOINT)
    if room <= target - deadband and running:
        return "COUPER la clim", dict(power=False)
    return "dans la bande", None


async def cycle(dev, args) -> None:
    # 1) ordre en attente (déposé par un autre outil via cache.queue_command)
    cmd = cache.pop_command()
    if cmd:
        await aclib.apply(dev, **cmd)
        print(f"  [cmd] appliqué: {cmd}", flush=True)

    # 2) lecture (on tient déjà la connexion -> pas de collision)
    await dev.refresh()
    st = aclib.snapshot(dev)
    # Netatmo (cloud) résilient : une panne ne doit JAMAIS empêcher de logger la Midea.
    try:
        nt = await asyncio.to_thread(netatmo.read)
    except Exception as e:
        nt = netatmo.Therm()
        print(f"  [netatmo indispo: {e}]", flush=True)
    now = datetime.now(timezone.utc)

    # météo ambiante (résiliente : ne casse pas le cycle si Open-Meteo échoue)
    ambient_temp = heat_delta = None
    try:
        amb = await asyncio.to_thread(weather.ambient)
        ambient_temp = amb.temp
        # Le capteur condenseur gèle en veille -> delta n'a de sens QUE
        # compresseur en marche. On se fie à power_w (la VÉRITÉ physique), car
        # power_state est peu fiable sur ce PortaSplit (lit OFF en cooling).
        cooling_now = (st.mode == "COOL"
                       and st.power_w is not None and st.power_w > 80)
        if ambient_temp is not None and st.outdoor_temp is not None and cooling_now:
            heat_delta = round(st.outdoor_temp - ambient_temp, 1)
    except Exception:
        pass

    # 3) publication du cache
    state = asdict(st)
    state.update(netatmo_temp=nt.measured_temp, netatmo_setpoint=nt.setpoint_temp,
                 netatmo_mode=nt.setpoint_mode, heating=nt.heating,
                 ambient_temp=ambient_temp, heat_delta=heat_delta,
                 room=nt.room_name, ts=now.isoformat(timespec="seconds"),
                 ts_epoch=now.timestamp())
    cache.write_state(state)

    # 4) historique CSV
    append_csv({
        "timestamp": now.isoformat(timespec="seconds"),
        "netatmo_temp": nt.measured_temp, "midea_temp": st.indoor_temp,
        "outdoor_temp": st.outdoor_temp, "ac_power": st.power, "ac_mode": st.mode,
        "ac_setpoint": st.target_temp, "power_w": st.power_w,
        "energy_kwh": st.energy_kwh, "netatmo_setpoint": nt.setpoint_temp,
        "netatmo_mode": nt.setpoint_mode, "heating": nt.heating,
        "ambient_temp": ambient_temp, "heat_delta": heat_delta,
    })

    line = (f"{now.strftime('%H:%M:%S')}  pièce {nt.measured_temp}°C  "
            f"unit {st.indoor_temp}°C  out {st.outdoor_temp}°C  {st.power_w}W")

    # 5) régulation optionnelle (même connexion, donc sûr)
    if args.control:
        action, props = regulate(nt.measured_temp, st, args.target, args.deadband)
        if props and args.apply:
            await aclib.apply(dev, **props)
            line += f"  -> {action} ✓"
        elif props:
            line += f"  -> {action} [DRY-RUN]"
        else:
            line += f"  -> {action}"
    print(line, flush=True)


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--interval", type=int, default=120)
    p.add_argument("--once", action="store_true")
    p.add_argument("--control", action="store_true", help="Réguler la pièce sur la sonde Netatmo")
    p.add_argument("--target", type=float, default=25.0)
    p.add_argument("--deadband", type=float, default=0.4)
    p.add_argument("--apply", action="store_true", help="Avec --control: pilote vraiment (sinon dry-run)")
    args = p.parse_args()

    if args.control:
        print(f"# Poller + régulation cible {args.target}°C "
              f"({'APPLY' if args.apply else 'DRY-RUN'})", flush=True)

    dev = None
    while True:
        try:
            if dev is None:
                dev = await aclib.connect()
            await cycle(dev, args)
        except Exception as e:
            print(f"[warn] cycle: {e}", file=sys.stderr, flush=True)
            dev = None  # forcer une reconnexion au prochain tour
        if args.once:
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    asyncio.run(main())
