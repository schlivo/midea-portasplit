"""Météo ambiante réelle via Open-Meteo (gratuit, sans clé).

Sert de référence "vrai extérieur" pour mesurer le heat-spot du condenseur
Midea : delta = capteur_condenseur - ambiant_vrai. Si ce delta MONTE quand le
compresseur tourne -> recirculation d'air chaud -> perte de rendement (idée B).
"""
from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Optional

import config

# Coordonnées du domicile (depuis .env)
LAT = config.get("HOME_LAT", 48.85, float)
LON = config.get("HOME_LON", 2.35, float)
UA = "midea-portasplit weather"


@dataclass
class Ambient:
    temp: Optional[float] = None
    humidity: Optional[float] = None
    wind_kmh: Optional[float] = None


def ambient() -> Ambient:
    url = (f"https://api.open-meteo.com/v1/forecast?latitude={LAT}&longitude={LON}"
           f"&current=temperature_2m,relative_humidity_2m,wind_speed_10m")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    cur = json.loads(urllib.request.urlopen(req, timeout=15).read())["current"]
    return Ambient(temp=cur.get("temperature_2m"),
                   humidity=cur.get("relative_humidity_2m"),
                   wind_kmh=cur.get("wind_speed_10m"))


if __name__ == "__main__":
    a = ambient()
    print(f"Neuilly-sur-Marne : {a.temp}°C, {a.humidity}% HR, vent {a.wind_kmh} km/h")
