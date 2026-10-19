"""Jarri AI-usage service: serves Claude token use and quota state to Jarri Workspace.

Backend only. Jarri's AI usage panel is a client of this service.

  GET /snapshot -> {now, fiveHourStart, sevenDayStart, tokens, limits}

tokens come from ~/.local/bin/ai-usage-tokens (summarises Claude Code transcripts).
limits come from ~/.local/state/ai-usage/latest.json, written by the Claude Code mod.
Binds to 127.0.0.1 only and accepts requests from the same allowed origins as the terminal service.
"""

import json
import os
import subprocess
import sys
import time
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

HOST = "127.0.0.1"
PORT = int(os.environ.get("JARRI_AI_USAGE_PORT", "8783"))
HOME = os.path.expanduser("~")
TOKENS_SCRIPT = os.path.join(HOME, ".local/bin/ai-usage-tokens")
LIMITS_FILE = os.path.join(HOME, ".local/state/ai-usage/latest.json")
HOUR_MS = 3_600_000
FIVE_HOURS_MS = 5 * HOUR_MS
SEVEN_DAYS_MS = 7 * 24 * HOUR_MS
ALLOWED_ORIGINS = {
    "tauri://localhost",
    "http://tauri.localhost",
    "https://tauri.localhost",
    "http://localhost:1420",
    "http://127.0.0.1:1420",
    "http://localhost:8792",
    "http://127.0.0.1:8792",
}
ALLOWED_HOSTS = {f"{HOST}:{PORT}", f"localhost:{PORT}"}


def snapshot():
    now = int(time.time() * 1000)
    five_hour_start = now - FIVE_HOURS_MS
    seven_day_start = now - SEVEN_DAYS_MS
    result = subprocess.run(
        [TOKENS_SCRIPT, str(five_hour_start), str(seven_day_start)],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "ai-usage-tokens failed")
    tokens = json.loads(result.stdout)
    limits = None
    try:
        with open(LIMITS_FILE, encoding="utf-8") as file:
            limits = json.load(file)
    except (OSError, json.JSONDecodeError):
        pass  # the quota file is optional
    return {
        "now": now,
        "fiveHourStart": five_hour_start,
        "sevenDayStart": seven_day_start,
        "tokens": tokens,
        "limits": limits,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "jarri-ai-usage"

    def log_message(self, fmt, *args):
        pass

    def _allowed(self):
        origin = self.headers.get("Origin")
        if origin is not None and origin not in ALLOWED_ORIGINS:
            return False
        return self.headers.get("Host") in ALLOWED_HOSTS

    def _send(self, status, body=None):
        self.send_response(status)
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        if body is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        raw = json.dumps(body).encode()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_OPTIONS(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden origin"})
        self._send(204)

    def do_GET(self):
        if not self._allowed():
            return self._send(403, {"error": "forbidden origin"})
        if urlparse(self.path).path != "/snapshot":
            return self._send(404, {"error": "not found"})
        try:
            self._send(200, snapshot())
        except Exception as error:  # report the failure to the panel
            self._send(500, {"error": str(error)})


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    print(f"jarri ai-usage service on http://{HOST}:{PORT}", file=sys.stderr)
    server.serve_forever()


if __name__ == "__main__":
    main()
