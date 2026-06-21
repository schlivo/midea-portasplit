#!/usr/bin/env python3
"""Local OAuth2 helper for the Netatmo Energy API.

Runs the authorization-code flow entirely on your machine:
  1. reads NETATMO_CLIENT_ID / NETATMO_CLIENT_SECRET from .env
  2. opens your browser to Netatmo's login/consent page
  3. captures the redirect on http://localhost:8765/callback
  4. exchanges the code for tokens
  5. writes NETATMO_REFRESH_TOKEN back into .env

Prereq: add this exact redirect URI to your app on dev.netatmo.com:
    http://localhost:8765/callback
"""
from __future__ import annotations

import http.server
import secrets
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

REDIRECT_URI = "http://localhost:8765/callback"
SCOPES = "read_thermostat write_thermostat"
AUTH_URL = "https://api.netatmo.com/oauth2/authorize"
TOKEN_URL = "https://api.netatmo.com/oauth2/token"
ENV_PATH = Path(__file__).with_name(".env")


def load_env() -> dict:
    env = {}
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def save_refresh_token(token: str) -> None:
    lines = ENV_PATH.read_text().splitlines()
    out, found = [], False
    for line in lines:
        if line.startswith("NETATMO_REFRESH_TOKEN="):
            out.append(f"NETATMO_REFRESH_TOKEN={token}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"NETATMO_REFRESH_TOKEN={token}")
    ENV_PATH.write_text("\n".join(out) + "\n")


def exchange_code(env: dict, code: str) -> dict:
    data = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "client_id": env["NETATMO_CLIENT_ID"],
        "client_secret": env["NETATMO_CLIENT_SECRET"],
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data, headers={
        "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/124.0 Safari/537.36"),
        "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
        "Accept": "application/json",
    })
    import json
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        raise SystemExit(f"Token exchange failed (HTTP {e.code}):\n{body}")


def main() -> None:
    env = load_env()
    if not env.get("NETATMO_CLIENT_ID") or not env.get("NETATMO_CLIENT_SECRET"):
        raise SystemExit("Fill NETATMO_CLIENT_ID and NETATMO_CLIENT_SECRET in .env first.")

    state = secrets.token_urlsafe(16)
    params = urllib.parse.urlencode({
        "client_id": env["NETATMO_CLIENT_ID"],
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "response_type": "code",
    })
    auth_link = f"{AUTH_URL}?{params}"

    result = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            q = urllib.parse.urlparse(self.path).query
            qs = urllib.parse.parse_qs(q)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if qs.get("state", [None])[0] != state:
                self.wfile.write(b"<h2>State mismatch - aborting.</h2>")
                return
            if "code" in qs:
                result["code"] = qs["code"][0]
                self.wfile.write(b"<h2>OK! Netatmo authorized. You can close this tab.</h2>")
            elif "error" in qs:
                result["error"] = qs.get("error_description", qs["error"])[0]
                self.wfile.write(b"<h2>Authorization failed. Check the terminal.</h2>")

        def log_message(self, *a):  # silence
            pass

    server = http.server.HTTPServer(("127.0.0.1", 8765), Handler)
    print("Opening your browser to authorize Netatmo...")
    print(f"If it doesn't open, paste this URL:\n{auth_link}\n")
    webbrowser.open(auth_link)
    while not result:
        server.handle_request()

    if "error" in result:
        raise SystemExit(f"Netatmo error: {result['error']}")

    print("Exchanging code for tokens...")
    tokens = exchange_code(env, result["code"])
    if "refresh_token" not in tokens:
        raise SystemExit(f"No refresh_token in response: {tokens}")
    save_refresh_token(tokens["refresh_token"])
    print("Saved NETATMO_REFRESH_TOKEN to .env  (access token expires in "
          f"{tokens.get('expires_in', '?')}s, auto-refreshed from now on).")
    print("Granted scopes:", tokens.get("scope"))


if __name__ == "__main__":
    main()
