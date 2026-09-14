"""
Process Maps — Core Model §03 "Canvas View" (in-app, first slice).

Renders every process in the model as a BPMN-style flow diagram: start -> tasks
-> end, with the agent-bound step highlighted, its guardrail escalation branch to
a human, task-level overrides marked, and a per-process header (owner, guardrail
version, KPIs, linked risk). Redrawn from the live graph on each load. Read-only.

Runs alongside governance (:8787) and dashboard (:8788).

    python3 app.py            # http://localhost:8789
    python3 app.py --port N
"""
from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
from mapdata import all_maps  # noqa: E402
import store as gov  # noqa: E402  — the tested guardrail write path (one source of truth)

STORE = gov.GovernanceStore()

STATIC = os.path.join(HERE, "static")
CONTENT = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
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

    def _json_code(self, obj, code):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/api/maps":
            g = cc.Graph()
            return self._json({"model_sig": g.model_sig, "processes": all_maps(g)})
        return self._static(u.path)

    def do_PUT(self):
        # edit a guardrail from the canvas — same tested write path as governance,
        # so the edit is versioned, on the §7.5 trail, and live for the redraw.
        u = urlparse(self.path)
        if u.path != "/api/guardrail":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            new = STORE.edit_guardrail(
                parse_qs(u.query).get("id", [""])[0],
                changes=payload.get("changes", {}), actor=payload.get("actor", "role.unknown"),
                reason=payload.get("reason", ""), reviewer=payload.get("reviewer", ""))
            return self._json({"ok": True, "guardrail": new})
        except gov.EditError as e:
            return self._json_code({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json_code({"ok": False, "error": repr(e)}, 500)


def main():
    port = 8789
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    print("Continuum Process Maps on http://localhost:8789")
    main()
