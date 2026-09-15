"""
Strategy-to-execution dashboard — Phase 4 (Core Model §05, §12).

The standing leadership report: what each objective's KPIs are doing, which tasks
below them run under an agent (with what guardrail and what the agent did), and
the §12 success metrics — read live from the same graph + agent action log the
rest of the system uses. Read-only; no writes.

Stdlib only. Run alongside the governance app (different port).

    python3 app.py            # http://localhost:8788
    python3 app.py --port N
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
import continuum_core as cc  # noqa: E402
from rollup import Rollup, load_agent_events  # noqa: E402

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
        if u.path == "/api/rollup":
            g = cc.Graph()
            r = Rollup(g)
            events = load_agent_events()
            return self._json({
                "model_sig": g.model_sig,
                "strategy": r.strategy(events),
                "bottom_up": r.bottom_up(events),
                "coverage": r.coverage(),
                "by_domain": r.by_domain(),
                "risk_register": r.risk_register(),
                "metrics": r.metrics(events),
            })
        return self._static(u.path)


def main():
    port = 8788
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    print("Continuum Dashboard on http://localhost:8788")
    main()
