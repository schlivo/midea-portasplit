"""Couche d'accès locale au Midea Portasplit (via msmart-ng).

Connexion + authentification une seule fois, puis lecture (avec conso) et
contrôle. Sert de fondation aux fonctions A/B/C/D (coût, watchdog, météo, budget).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, asdict
from typing import Optional

from msmart.base_device import Device
from msmart.const import DeviceType
from msmart.device import AirConditioner as AC

import config

# --- Identifiants de l'appareil (depuis .env ; obtenus une fois via le cloud EU) ---
HOST = config.get("MIDEA_HOST")
PORT = config.get("MIDEA_PORT", 6444, int)
DEVICE_ID = config.get("MIDEA_DEVICE_ID", cast=int)
TOKEN = config.get("MIDEA_TOKEN")
KEY = config.get("MIDEA_KEY")


@dataclass
class State:
    """Instantané de l'état utile, prêt à logger/analyser."""
    power: Optional[bool] = None
    mode: Optional[str] = None
    target_temp: Optional[float] = None
    indoor_temp: Optional[float] = None
    outdoor_temp: Optional[float] = None
    fan_speed: Optional[int] = None
    eco: Optional[bool] = None
    turbo: Optional[bool] = None
    power_w: Optional[float] = None        # puissance instantanée (W)
    energy_kwh: Optional[float] = None     # cumul (kWh)
    error_code: Optional[int] = None


async def connect(energy: bool = True) -> AC:
    """Construit, authentifie et retourne l'appareil prêt à l'emploi."""
    dev = Device.construct(type=DeviceType.AIR_CONDITIONER,
                           ip=HOST, port=PORT, device_id=DEVICE_ID)
    await dev.authenticate(TOKEN, KEY)
    if energy and hasattr(dev, "enable_energy_usage_requests"):
        dev.enable_energy_usage_requests = True
    return dev


def snapshot(dev: AC) -> State:
    """Lit l'état courant de l'objet déjà rafraîchi (après dev.refresh())."""
    return State(
        power=dev.power_state,
        mode=getattr(dev.operational_mode, "name", None),
        target_temp=dev.target_temperature,
        indoor_temp=dev.indoor_temperature,
        outdoor_temp=dev.outdoor_temperature,
        fan_speed=int(dev.fan_speed) if dev.fan_speed is not None else None,
        eco=dev.eco,
        turbo=dev.turbo,
        # CE MODÈLE encode en BINARY, pas BCD (le défaut) : le BCD sous-lit ~3-4×.
        # Confirmé en comparant à l'app (1036/1042 W = BINARY, pas BCD ~290 W).
        power_w=dev.get_real_time_power_usage(AC.EnergyDataFormat.BINARY),
        energy_kwh=dev.get_total_energy_usage(AC.EnergyDataFormat.BINARY),
        error_code=dev.error_code,
    )


async def read() -> State:
    """Helper one-shot : connecte, rafraîchit, renvoie l'instantané."""
    dev = await connect()
    await dev.refresh()
    return snapshot(dev)


async def apply(dev: AC, *, power: Optional[bool] = None,
                mode: Optional[str] = None, target: Optional[float] = None,
                fan: Optional[str] = None, eco: Optional[bool] = None,
                turbo: Optional[bool] = None, swing: Optional[str] = None) -> None:
    """Applique des réglages à un appareil déjà connecté (None = inchangé)."""
    if power is not None:
        dev.power_state = power
    if mode is not None:
        dev.operational_mode = AC.OperationalMode[mode.upper()]
    if eco is not None:
        dev.eco = eco          # l'éco bride/clampe la consigne -> à couper pour forcer le froid
    if turbo is not None:
        dev.turbo = turbo
    if swing is not None:
        dev.swing_mode = AC.SwingMode[swing.upper()]  # OFF = volet fixe (silencieux)
    if target is not None:
        dev.target_temperature = float(target)
    if fan is not None:
        dev.fan_speed = AC.FanSpeed[fan.upper()]
    await dev.apply()


if __name__ == "__main__":
    st = asyncio.run(read())
    for k, v in asdict(st).items():
        print(f"{k:>12} : {v}")
