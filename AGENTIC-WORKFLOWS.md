# 🤖 Agentified workflows — how this was built

This whole project was built in a running conversation with an AI coding agent
([Claude Code](https://claude.com/claude-code)) — from *"I wonder if I can do
cool things with my AC?"* to a self-regulating, logged, multi-vendor system.
This is the **method**, so you can drive your own hardware exploration the same way.

The agent isn't writing code from a spec — it's **reverse-engineering live
hardware** through a tight loop. That changes how you work with it.

## The core loop

```
   probe ──▶ research ──▶ build ──▶ verify against ground truth ──▶ record
     ▲                                                                │
     └────────────────────────  next unknown  ◀──────────────────────┘
```

1. **Probe** — `ping`, port scan, a one-shot read. Establish what's actually there.
2. **Research** — pull the protocol/library/API docs (don't trust memory for
   versioned details — fetch them).
3. **Build the smallest thing** — one function, run it, see real output.
4. **Verify against ground truth** — the single most important habit. The vendor
   app, a multimeter, a known value. *This is how we caught the BINARY power bug
   that silently wrong-ified every reading by 3–4×.* If a number looks off, it is.
5. **Record the finding** — in durable memory (see below), not just the chat.

## Patterns that made it work

### Persistent memory beats a long chat
The agent kept a file-based memory of every non-obvious fact (the protocol
quirks, the device IDs, "eco overrides fan", "power is BINARY not BCD"). Next
session it recalls them instead of re-deriving. **Write findings to disk, keyed
and searchable** — chat scrollback is not a knowledge base. (`FINDINGS.md` is the
human-readable distillation of that.)

### Single-owner + cache for fragile devices
The Midea tolerates one TCP connection. Rather than sprinkle connections, **one
daemon owns the device** and publishes `state.json`; everything else reads the
cache and *queues* commands. One hardware constraint → one architectural rule.
Let the agent discover the constraint empirically, then encode it once.

### Resilience is not optional — it's the default
Long-running daemons meet flaky clouds. We learned (the hard way, mid-run) to:
- never let a cloud `503` or `SystemExit` kill the loop;
- log the *local* device even when the *cloud* part is down;
- return empty-but-valid objects instead of crashing on missing data.
Each of these was a live failure the agent saw and patched. **Run it for real,
in the background, and fix what actually breaks** — not what you imagine might.

### Background tasks + observe
The poller runs in the background across turns; the agent checks its output,
notices the crash-loop, diagnoses, restarts. Treat the agent as an operator, not
just an author: it can watch logs and react.

### Dry-run before actuating hardware
Anything that moves a compressor or a valve ran in **dry-run** first (print the
decision, don't send it), then `--apply`. Cheap insurance on physical systems.

### Let dead ends be data
"Turbo doesn't work" / "OUT_SILENT is invisible" / "that 3.2 V battery would fry
it" — the *negative* results are half the value. Record them so neither you nor
the agent retries them.

## Setting it up yourself (Claude Code)

- **Give the agent durable memory.** Point it at a project memory dir and tell it
  to record findings as it goes. It will recall them next session.
- **Let it run things in the background** (pollers, captures) and report back.
- **Keep secrets in `.env`** from the start — the agent will respect it, and your
  repo stays shareable (this one moved every credential out of code into
  `config.py` + `.env`).
- **Ask for verification.** "Compare that to the app." "Sanity-check the
  magnitude." The agent is good at it when prompted; great habits come from you
  asking.
- **Work in small, reversible steps.** One probe, one function, one finding at a
  time. The big wins (the BINARY fix) came from noticing a small discrepancy, not
  from a grand plan.

## The shape of a session

> probe the device → it answers on the Midea port → research msmart-ng →
> read state → "wait, that power looks low" → compare to the app → it's
> BCD-vs-BINARY → fix + back-convert the history → record it → move to the
> next unknown.

Multiply that by a few dozen and you get this repo. None of it was planned up
front; all of it was **discovered, verified, and written down**.
