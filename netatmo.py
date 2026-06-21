"""Netatmo Energy API reader (thermostat) — cloud, OAuth2.

Refreshes the access token from the stored refresh token, and CRUCIALLY
persists the rotated refresh token back to .env every time (Netatmo rotates
it on each refresh; failing to save it => invalid_grant on next run).

Exposes the live room temperature, setpoint and heating state — meant to be
the temperature *reference* for the unified heat/cool controller.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

API = "https://api.netatmo.com"
TOKEN_URL = f"{API}/oauth2/token"
import config
TARGET_ROOM = config.get("NETATMO_TARGET_ROOM", "Séjour")  # pièce où est la Midea
ENV_PATH = Path(__file__).with_name(".env")
# Browser-like UA: Netatmo's Azure Front Door WAF blocks default python-urllib.
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


def _load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def _save_env_value(key: str, value: str) -> None:
    lines = ENV_PATH.read_text().splitlines()
    out, found = [], False
    for line in lines:
        if line.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def _post(url: str, params: dict, token: Optional[str] = None) -> dict:
    data = urllib.parse.urlencode(params).encode()
    headers = {"User-Agent": UA,
               "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
               "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        # RuntimeError (pas SystemExit) : un daemon doit pouvoir l'attraper
        # et survivre à une panne transitoire (ex: 503 Netatmo).
        raise RuntimeError(f"Netatmo HTTP {e.code} on {url}: "
                           f"{e.read().decode('utf-8','replace')[:200]}")


def access_token() -> str:
    """Refresh and return an access token; persist the rotated refresh token."""
    env = _load_env()
    resp = _post(TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": env["NETATMO_REFRESH_TOKEN"],
        "client_id": env["NETATMO_CLIENT_ID"],
        "client_secret": env["NETATMO_CLIENT_SECRET"],
    })
    # Netatmo rotates the refresh token on every refresh — save the new one.
    new_rt = resp.get("refresh_token")
    if new_rt and new_rt != env["NETATMO_REFRESH_TOKEN"]:
        _save_env_value("NETATMO_REFRESH_TOKEN", new_rt)
    return resp["access_token"]


@dataclass
class Therm:
    home_id: Optional[str] = None
    home_name: Optional[str] = None
    room_id: Optional[str] = None
    room_name: Optional[str] = None
    measured_temp: Optional[float] = None   # actual room temperature (°C)
    setpoint_temp: Optional[float] = None    # target temperature (°C)
    setpoint_mode: Optional[str] = None      # schedule / manual / away / hg / off
    heating: Optional[bool] = None           # boiler currently firing


def read() -> Therm:
    tok = access_token()
    # 1) Topology: find the home + first thermostat room
    homes = _post(f"{API}/api/homesdata", {}, tok)
    home = homes["body"]["homes"][0]
    home_id, home_name = home["id"], home.get("name")
    rooms_meta = {r["id"]: r.get("name") for r in home.get("rooms", [])}

    # 2) Live status
    status = _post(f"{API}/api/homestatus", {"home_id": home_id}, tok)
    rooms = status["body"]["home"].get("rooms", [])
    # Cibler le SÉJOUR (où se trouve la Midea), pas "la première pièce" — sinon
    # la référence dérive quand d'autres capteurs reviennent en ligne.
    target_id = next((rid for rid, name in rooms_meta.items()
                      if (name or "").strip().lower() == TARGET_ROOM.lower()), None)
    room = (next((r for r in rooms if r.get("id") == target_id), None)
            or next((r for r in rooms if "therm_measured_temperature" in r), None))
    if room is None:
        # homestatus vide (relais/vannes hors-ligne ?) -> pas de mesure, sans crash
        return Therm(home_id=home_id, home_name=home_name, room_id=None,
                     room_name=None, measured_temp=None, setpoint_temp=None,
                     setpoint_mode=None, heating=None)
    rid = room["id"]
    return Therm(
        home_id=home_id, home_name=home_name,
        room_id=rid, room_name=rooms_meta.get(rid),
        measured_temp=room.get("therm_measured_temperature"),
        setpoint_temp=room.get("therm_setpoint_temperature"),
        setpoint_mode=room.get("therm_setpoint_mode"),
        heating=bool(room.get("heating_power_request", 0)) if "heating_power_request" in room else None,
    )


def read_all() -> list[Therm]:
    """Tous les capteurs/vannes du domicile (utile quand les autres pièces
    reviennent en ligne après changement de piles)."""
    tok = access_token()
    homes = _post(f"{API}/api/homesdata", {}, tok)
    home = homes["body"]["homes"][0]
    home_id, home_name = home["id"], home.get("name")
    rooms_meta = {r["id"]: r.get("name") for r in home.get("rooms", [])}
    status = _post(f"{API}/api/homestatus", {"home_id": home_id}, tok)
    out = []
    for r in status["body"]["home"].get("rooms", []):
        if "therm_measured_temperature" not in r:
            continue
        out.append(Therm(
            home_id=home_id, home_name=home_name,
            room_id=r["id"], room_name=rooms_meta.get(r["id"]),
            measured_temp=r.get("therm_measured_temperature"),
            setpoint_temp=r.get("therm_setpoint_temperature"),
            setpoint_mode=r.get("therm_setpoint_mode"),
            heating=bool(r.get("heating_power_request", 0)) if "heating_power_request" in r else None,
        ))
    return out


if __name__ == "__main__":
    from dataclasses import asdict
    import sys
    if "--all" in sys.argv:
        for t in read_all():
            print(f"{t.room_name:>12} : {t.measured_temp}°C  (consigne {t.setpoint_temp}°C, {t.setpoint_mode})")
    else:
        for k, v in asdict(read()).items():
            print(f"{k:>15} : {v}")
