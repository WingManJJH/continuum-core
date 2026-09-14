"""
Ask the Agent — the in-app window where you ask a plain-English question about the
model and the agent writes a read-only graph query, runs it, and answers with a
table, its assumptions, and the exact query it ran (Show query).

Backed by the deterministic IntentPlanner + a real read-only QueryEngine. The
LLMPlanner seam is where a live model plugs in for arbitrary questions once auth
exists.

    python3 app.py            # http://localhost:8791
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
from agent import Agent  # noqa: E402

STATIC = os.path.join(HERE, "static")
CONTENT = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        fname = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, fname))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self.send_error(404)
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/examples":
            return self._json({"examples": Agent().examples()})
        return self._static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/ask":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(length) or b"{}")
        try:
            # a fresh Agent per request => reads the latest graph + edit log
            return self._json(Agent().ask(b.get("question", "")))
        except Exception as e:  # noqa: BLE001
            return self._json({"error": repr(e)}, 500)


def main():
    port = 8791
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    print("Continuum · Ask the Agent on http://localhost:8791")
    main()
