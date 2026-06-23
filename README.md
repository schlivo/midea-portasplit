# 🌡️ Portasplit — local-first home climate & energy toolkit

A small fleet of Python scripts that take **local control** of a Midea
*PortaSplit* air conditioner, cross-reference it with a **Netatmo** thermostat
and real **weather** — and turn it all into a logged, analysable,
*self-regulating* system.

It was built end-to-end in conversation with an AI coding agent (Claude Code),
as an experiment in **agent-driven reverse engineering + home automation**. The
whole back-and-forth — every dead end, every "wait, that reading is wrong" — is
distilled into [`FINDINGS.md`](FINDINGS.md), and the *method* into
[`AGENTIC-WORKFLOWS.md`](AGENTIC-WORKFLOWS.md).

> ⚠️ Everything here drives **your own devices on your own network**. No cloud
> lock-in: the AC is controlled 100% locally; only Netatmo and Enedis need their
> (free) clouds, because those vendors expose no local API.

---

## What it does

- **Local AC control & telemetry** — power on/off, mode, setpoint, eco, fan,
  louver; live power draw (W) and temperatures, with **no cloud**.
- **Cross-brand thermostat** — holds the *real* room temperature (from the
  accurate Netatmo sensor) by driving the Midea, correcting the AC's own
  ~1 °C-biased sensor. Neither vendor's app can do this.
- **Single-owner poller** — one process owns the (single-connection) AC, polls
  every 2 min, writes a `state.json` cache + a CSV history, and optionally
  regulates inline. Everything else reads the cache (no collisions).
- **True-ambient heat-spot watchdog** — compares the condenser sensor to
  Open-Meteo's real outdoor temp to detect exhaust recirculation / efficiency
  loss.
- **Whole-home view** — every Netatmo room, valve battery & RF health.

## Architecture

```
                  ┌─────────────┐
   Midea AC ◄─────┤  poller.py  │  ← the ONLY process that talks to the AC
   (1 conn)       │  (daemon)   │     polls · logs CSV · regulates
                  └──────┬──────┘
                         │ writes
                  ┌──────▼───────┐
                  │  state.json  │  ← cache
                  │ command.json │  ← command queue
                  └──────┬───────┘
                         │ read / queue (no device access)
        ┌────────────────┼─────────────────┐
   thermostat.py    watchdog.py        your tools
```

| File | Role |
|---|---|
| `config.py` | loads `.env` (no secrets in code) |
| `aclib.py` | Midea connect / read / control (msmart-ng) |
| `netatmo.py` | Netatmo Energy API reader (OAuth2, token rotation) |
| `weather.py` | Open-Meteo true-ambient |
| `cache.py` | `state.json` + `command.json` IPC |
| `poller.py` | **single-owner daemon**: poll · log · cache · regulate |
| `thermostat.py` | cache consumer; queues commands |
| `watchdog.py` | condenser heat-spot / recirculation check |
| `advisor.py` | heat-wave ventilation advisor: per-room open/close vs weather + forecast, `--watch` for desktop alerts |
| `netatmo_auth.py` | one-time Netatmo OAuth helper |
| `clim` | quick shell wrapper |
| `enedis.py` / `enedis_export.py` / `conso.py` | *optional* — read your electricity-meter data (see below) |

## Extending it

The core is local AC control + the Netatmo/weather cross-reference. Everything
else is an **optional integration that depends on your personal setup** — wire in
whatever data sources you have. The included `enedis.py` / `conso.py` /
`enedis_export.py` are an **example**: they pull electricity-meter consumption
(French Enedis grid, three different ways — manual `.xlsx`, the conso.boris.sh
proxy, or a Playwright portal scrape) so you can correlate house energy with the
climate logs. Swap in your own utility, PV inverter, smart plugs, etc. — the
poller's CSV/cache make it easy to fuse new feeds.

## Setup

```bash
# 1. deps (uv: https://docs.astral.sh/uv/)
uv sync                       # or: uv add msmart-ng openpyxl playwright pyyaml

# 2. config
cp .env.example .env          # then fill it in (see below)

# 3. get the Midea local token/key (once, via the EU cloud)
uv run msmart-ng discover --region DE <device-ip>
#   -> copy id / token / key into .env (MIDEA_*)

# 4. Netatmo OAuth (once)
#   create an app at dev.netatmo.com, put client id/secret in .env, then:
uv run python netatmo_auth.py # opens a browser, writes the refresh token

# 5. go
uv run python aclib.py        # read the AC
./clim                        # quick status
./clim cool 24                # control
uv run python poller.py       # start logging
uv run python poller.py --control --target 24 --apply   # + regulate
```

See [`AGENTIC-WORKFLOWS.md`](AGENTIC-WORKFLOWS.md) for how this was built with an
agent and how to drive your own exploration the same way.

## Credits & prior art

- [`msmart-ng`](https://github.com/mill1000/midea-msmart) — Midea local protocol
- [Open-Meteo](https://open-meteo.com/) — free weather API
- [conso.boris.sh](https://conso.boris.sh) / [MyElectricalData](https://myelectricaldata.fr/) — Enedis proxies (optional)
- Built with [Claude Code](https://claude.com/claude-code)

## License

MIT — do whatever, no warranty. It controls real hardware; you own the consequences.
