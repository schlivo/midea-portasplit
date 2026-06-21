"""Watchdog heat-spot du condenseur Midea — version honnête.

N'utilise QUE les échantillons où la clim refroidit vraiment (power_w > 80),
car le capteur extérieur gèle en veille (lecture inutile). Mesure :
  delta = capteur_condenseur - ambiant_vrai (Open-Meteo)
et teste la corrélation delta~puissance :
  - corrélation POSITIVE + delta élevé  -> recirculation d'air chaud (à corriger)
  - delta plat ou décroissant           -> pas de pénalité détectable

Usage:  uv run python watchdog.py
"""
from __future__ import annotations

import csv
import statistics as st
from pathlib import Path

CSV = Path(__file__).with_name("climate_log.csv")
COOLING_W = 80.0


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def load_cooling() -> list[tuple[float, float]]:
    """[(power_w, heat_delta)] sur les échantillons en refroidissement actif."""
    out = []
    for r in csv.DictReader(open(CSV)):
        p, d = _f(r.get("power_w")), _f(r.get("heat_delta"))
        if p is not None and d is not None and p > COOLING_W:
            out.append((p, d))
    return out


def pearson(xs, ys) -> float:
    n = len(xs)
    if n < 3:
        return float("nan")
    mx, my = st.mean(xs), st.mean(ys)
    cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sx = sum((x - mx) ** 2 for x in xs) ** 0.5
    sy = sum((y - my) ** 2 for y in ys) ** 0.5
    return cov / (sx * sy) if sx and sy else float("nan")


def report() -> None:
    data = load_cooling()
    if len(data) < 5:
        print(f"Pas assez de données en refroidissement actif (n={len(data)}). "
              "Attendre un après-midi chaud avec la clim qui tourne.")
        return
    ps = [p for p, _ in data]
    ds = [d for _, d in data]
    r = pearson(ps, ds)
    print(f"Échantillons clim active (>{COOLING_W:.0f}W) : {len(data)}")
    print(f"Heat-delta moyen : {st.mean(ds):+.1f}°C  (min {min(ds):+.1f} / max {max(ds):+.1f})")
    print(f"Puissance : {st.mean(ps):.0f}W moy ({min(ps):.0f}-{max(ps):.0f})")
    print(f"Corrélation delta~puissance : r = {r:+.2f}")
    print()
    if r > 0.4 and st.mean(ds) > 3:
        print("⚠️  RECIRCULATION probable : le delta monte avec la charge.")
        print("   -> améliorer l'aération du condenseur (surélever, dégager) devrait aider.")
    elif r > 0.4:
        print("~ Léger signe de recirculation (delta corrèle mais reste modéré).")
    else:
        print("✅ Pas de pénalité de recirculation détectable (delta ne suit pas la charge).")
        print("   -> surélever le condenseur n'apportera probablement pas de gain mesurable.")


if __name__ == "__main__":
    report()
