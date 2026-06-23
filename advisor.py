"""Conseiller de ventilation canicule.

Croise la météo (Open-Meteo : actuel + prévision horaire) avec les températures
par pièce (Netatmo) et dit, pièce par pièce, s'il faut OUVRIR (dehors plus frais
→ ventiler) ou FERMER (dehors plus chaud → garder le frais). Donne aussi le mode
global jour/nuit et l'heure de la prochaine bascule.

Usage:
  uv run python advisor.py              # conseil une fois
  uv run python advisor.py --watch      # boucle + notif macOS quand le conseil change
  uv run python advisor.py --watch --interval 1800
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
import urllib.request

import netatmo
import weather

MARGIN = 0.5  # °C : hystérésis pour éviter le yo-yo ouvre/ferme
TZ = "Europe/Paris"


def hourly_forecast() -> list[tuple[dt.datetime, float]]:
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={weather.LAT}"
           f"&longitude={weather.LON}&hourly=temperature_2m&forecast_days=2&timezone={TZ}")
    req = urllib.request.Request(url, headers={"User-Agent": "advisor"})
    h = json.loads(urllib.request.urlopen(req, timeout=15).read())["hourly"]
    return [(dt.datetime.fromisoformat(t), v)
            for t, v in zip(h["time"], h["temperature_2m"])]


def recommend() -> dict:
    rooms = [r for r in netatmo.read_all() if r.measured_temp is not None]
    amb = weather.ambient().temp
    fc = hourly_forecast()
    now_local = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)).replace(tzinfo=None)
    coolest = min(r.measured_temp for r in rooms)
    warmest = max(r.measured_temp for r in rooms)

    if amb >= warmest - MARGIN:
        mode = "JOUR — ferme tout + volets"
    elif amb <= coolest + MARGIN:
        mode = "NUIT — ouvre tout, clim off"
    else:
        mode = "MIXTE"

    per_room = []
    for r in sorted(rooms, key=lambda x: x.measured_temp):
        d = amb - r.measured_temp
        state = "OUVRE" if d <= -MARGIN else ("ferme" if d >= MARGIN else "neutre")
        per_room.append((r.room_name, r.measured_temp, state, round(d, 1)))

    future = [(t, v) for t, v in fc if t > now_local]
    peak = max(future[:18], key=lambda x: x[1]) if future else None
    cross = next((t for t, v in future if v <= coolest), None)
    return {"ambient": amb, "mode": mode, "rooms": per_room,
            "peak": peak, "next_night": cross, "coolest": coolest}


def render(rec: dict) -> None:
    icon = {"OUVRE": "🟢", "ferme": "🔵", "neutre": "⚪"}
    print(f"=== CONSEIL VENTILATION  (dehors {rec['ambient']}°C) ===\n")
    print(f"MODE : {rec['mode']}\n\nPar pièce :")
    for name, t, state, d in rec["rooms"]:
        print(f"  {name:<16} {t:>4}°C   {icon[state]} {state:<6} (dehors {d:+.1f})")
    if rec["peak"]:
        print(f"\nPrévision : pic {rec['peak'][1]:.0f}°C vers {rec['peak'][0].strftime('%Hh')}.")
    if rec["next_night"]:
        print(f"➡️  Bascule NUIT (dehors < {rec['coolest']}°C) : ~{rec['next_night'].strftime('%Hh')} "
              "→ ouvre tout, coupe la clim.")
    else:
        print(f"➡️  Dehors ne repasse pas sous {rec['coolest']}°C sous 18h (nuit chaude) — clim indispensable.")


def notify(title: str, msg: str) -> None:
    """Notification macOS (osascript). Sans effet ailleurs."""
    try:
        subprocess.run(["osascript", "-e",
                        f'display notification "{msg}" with title "{title}"'],
                       check=False, capture_output=True)
    except FileNotFoundError:
        pass


def _signature(rec: dict) -> tuple:
    """Ce qui définit un 'changement de conseil' : le mode + l'état de chaque pièce."""
    return (rec["mode"], tuple((n, s) for n, _, s, _ in rec["rooms"]))


def watch(interval: int) -> None:
    print(f"# Surveillance ventilation (toutes les {interval//60} min) — notif macOS aux changements\n")
    prev = None
    while True:
        try:
            rec = recommend()
            sig = _signature(rec)
            ts = time.strftime("%H:%M")
            if sig != prev:
                changed = [f"{n}:{s}" for (n, _, s, _) in rec["rooms"]]
                print(f"\n🔔 {ts} CHANGEMENT — mode {rec['mode']}")
                render(rec)
                notify("Ventilation", f"{rec['mode']} | " + ", ".join(
                    f"{n} {s}" for n, _, s, _ in rec["rooms"] if s != "neutre"))
                prev = sig
            else:
                print(f"  {ts}  (inchangé — {rec['mode']})", flush=True)
        except Exception as e:
            print(f"[warn] {e}", file=sys.stderr, flush=True)
        time.sleep(interval)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--watch", action="store_true")
    p.add_argument("--interval", type=int, default=1800)
    args = p.parse_args()
    if args.watch:
        watch(args.interval)
    else:
        render(recommend())


if __name__ == "__main__":
    main()
