# 🔬 Findings — the hard-won quirks

Everything we learned reverse-engineering this setup. If you have the same gear,
this will save you days. Most of it is **not** in any datasheet.

## Midea PortaSplit — local protocol (via `msmart-ng`)

### ⚡ Power/energy is BINARY-encoded, not BCD (the big one)
`msmart` defaults to **BCD** for `real_time_power_usage` / `total_energy_usage`.
This unit uses **BINARY**. BCD **under-reads by ~3–4×**. We only caught it because
the official app showed **1036 W** while our BCD read said ~290 W.

- Fix: `get_real_time_power_usage(AC.EnergyDataFormat.BINARY)`.
- Reversible conversion (verified to the watt):
  `binary = int(str(round(bcd*10)), 16) / 10`
- Real draw: **avg ~300 W, peak ~1034 W** (turbo) — i.e. the AC is a *major*
  load, comparable to a gaming PC, not the "sips power" we first assumed.
- **Lesson:** always sanity-check telemetry against the vendor app. A
  suspiciously-low number probably means a decode/format bug.

### `power_state` is unreliable
Reads `False` while the compressor is clearly running (100 W+). **Trust
`power_w`** as ground truth (standby ≈ 2 W, cooling 100–1000 W). All "is it on /
cooling" logic keys off wattage, not the flag.

### `eco` reads unreliably too
The cached `eco` flag sometimes shows `False` while it's actually on. A fresh
direct read is more trustworthy than the poller cache for `eco`.

### Setpoint has a *configurable* floor on the unit
We couldn't set below 24 °C — turned out to be the unit's own **temperature-range
setting**. Widen it on the device (e.g. 18–26 °C) and sub-24 setpoints work. The
`min_target_temperature` capability (16) does **not** reflect this device-side limit.

### `turbo` — readable, not writable (locally)
Setting turbo over the local protocol is **ignored**. But the flag **is** readable
and reflects the app's state. So: log it, can't set it. (Near setpoint with a
silent fan, turbo also barely changes power — it's a pull-down booster.)

### `OUT_SILENT` (outdoor-unit quiet mode) — fully invisible locally
Advertised in capabilities, but **neither writable nor readable** — stays `False`
even after enabling it in the app. Cloud/app only.

### Combined commands conflict — send conflicting settings separately
- `eco=True` + `fan=...` in one command → eco grabs the fan (forces MAX).
- `eco` + `target` together → target gets clamped.
- Set `fan` / `target` in their **own** `apply()` call. (`aclib.apply` exposes
  each; the regulator re-asserts idempotently each cycle.)

### One TCP connection at a time
Concurrent local queries corrupt each other (`Error packet received`, garbage
like `0W / AUTO / 17°C`). Hence the **single-owner poller** + `state.json` cache
architecture — nothing else opens a second connection.

### Sensors
- The **indoor** sensor reads ~1 °C **cooler** than a well-placed room sensor
  (it's on the unit). The Netatmo-referenced thermostat exists to correct this.
- The **outdoor/condenser** sensor is real and live (`outdoor_temp`) — but it
  **freezes** when the compressor is off (held one value for 7 h overnight while
  ambient fell 3 °C). Only trust it while actively cooling (`power_w > 80`).
- Fan MAX ≈ fan SILENT for achieved room temp here, but MAX burns ~40 % more
  watts + noise. The compressor capacity vs heat load is the bottleneck, not the
  fan. **Silent is the smart default.**

## Netatmo (Energy / thermostat)

- **No local API.** The valves/thermostat talk **868 MHz RF** to a **relay
  (NAPlug)** which bridges to the cloud over WiFi. Everything is cloud-only.
- **Refresh-token rotation:** every token refresh returns a *new* refresh token
  and invalidates the old one (RFC 6749 §10.4). Persist it every time or you get
  `invalid_grant`. `netatmo.py` writes it back to `.env`.
- **Azure WAF** fronts the API and blocks the default python-urllib User-Agent —
  send a browser-like UA. A Chrome **extension** also mangled the OAuth consent
  enough to trip the WAF; doing it in a clean Safari window worked.
- **503s happen.** `homestatus` can return empty rooms/modules (whole home goes
  dark) during outages — handle it without crashing (`netatmo.read()` returns an
  empty `Therm`; the poller logs the AC regardless).
- **Room targeting:** pick your room **by name**, not "first room with a temp" —
  as valves come online the order changes and the reference drifts.
- **Relay placement** optimizes the **RF-to-valves** link (868 MHz), *not* WiFi —
  putting it next to an AP for "good WiFi" can starve the far rooms. Watch
  per-valve `rf_strength`.
