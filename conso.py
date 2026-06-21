"""Client Conso API (bokub) — proxy Enedis DataConnect (conso.boris.sh).

Récupère AUTOMATIQUEMENT (plus de .xlsx manuel) :
  - conso quotidienne (kWh/jour)
  - courbe de charge 30 min (W moyens) -> permet le plancher 3h-5h
Token Bearer perso depuis conso.boris.sh, dans .env (CONSO_TOKEN).
Données dispo le lendemain ~8h. start inclus, end exclu, format YYYY-MM-DD.

Usage:
  uv run python conso.py daily 2026-05-01 2026-06-19
  uv run python conso.py curve 2026-06-18 2026-06-20      # courbe 30 min
  uv run python conso.py floor 2026-06-18 2026-06-20      # plancher nuit 2h-5h
"""
from __future__ import annotations

import datetime as dt
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

BASE = "https://conso.boris.sh/api"
ENV_PATH = Path(__file__).with_name(".env")


def _env() -> dict:
    e = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            e[k.strip()] = v.strip()
    return e


def fetch(kind: str, start: str, end: str) -> dict:
    e = _env()
    tok, prm = e.get("CONSO_TOKEN"), e.get("CONSO_PRM")
    if not tok:
        raise SystemExit("CONSO_TOKEN manquant dans .env (jeton depuis conso.boris.sh).")
    url = f"{BASE}/{kind}?prm={prm}&start={start}&end={end}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {tok}",
                                               "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as ex:
        raise SystemExit(f"Conso API HTTP {ex.code}: {ex.read().decode('utf-8','replace')[:300]}")


def _readings(payload: dict) -> list[tuple[str, float]]:
    """[(date_str, value)] depuis interval_reading (value en str)."""
    rd = payload.get("interval_reading", payload.get("data", []))
    out = []
    for it in rd:
        v = it.get("value")
        d = it.get("date")
        if v is not None and d is not None:
            out.append((d, float(v)))
    return out


def daily(start: str, end: str) -> list[tuple[dt.date, float]]:
    """conso quotidienne -> (date, kWh).  value en Wh."""
    return [(dt.datetime.strptime(d[:10], "%Y-%m-%d").date(), v / 1000)
            for d, v in _readings(fetch("daily_consumption", start, end))]


def load_curve(start: str, end: str) -> list[tuple[dt.datetime, float]]:
    """courbe de charge 30 min -> (datetime, W moyens)."""
    out = []
    for d, v in _readings(fetch("consumption_load_curve", start, end)):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                out.append((dt.datetime.strptime(d, fmt), v)); break
            except ValueError:
                pass
    return out


def night_floor(curve: list[tuple[dt.datetime, float]], s=2, e=5) -> dict:
    night = [v for t, v in curve if s <= t.hour < e]
    if not night:
        return {"note": "pas de points nuit"}
    night.sort()
    return {"samples": len(night), "floor_w_min": round(night[0]),
            "floor_w_median": round(night[len(night) // 2])}


if __name__ == "__main__":
    if len(sys.argv) < 4:
        sys.exit("Usage: uv run python conso.py {daily|curve|floor} START END")
    mode, start, end = sys.argv[1], sys.argv[2], sys.argv[3]
    if mode == "daily":
        for d, v in daily(start, end):
            print(f"{d}  {v:.1f} kWh")
    elif mode == "curve":
        c = load_curve(start, end)
        print(f"{len(c)} points 30 min ({c[0][0]} -> {c[-1][0]})")
        for t, v in c[:6]:
            print(f"  {t}  {v:.0f} W")
        print("  ...")
    elif mode == "floor":
        print("Plancher nuit 2h-5h:", night_floor(load_curve(start, end)))
