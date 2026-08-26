"""
Continuum Governance module — Phase 2 web app (Core Model §09 Phase 2).

The place a process owner edits a Guardrail Policy without an engineering ticket:
browse processes, open a guardrail, change what the agent may do / must escalate /
can touch, save a new version with a reason, and see the version history, the
linked risk & control, and the ISO 9001 §7.5 audit trail.

Stdlib only (http.server) + the governance store. No build step, no npm.

    python3 app.py            # serves http://localhost:8787
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
import store as gov  # noqa: E402

STATIC = os.path.join(HERE, "static")
STORE = gov.GovernanceStore()
CONTENT = {".html": "text/html", ".js": "text/javascript",
           ".css": "text/css", ".json": "application/json"}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # quiet
        pass

    # --- responses ---------------------------------------------------------
    def _json(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _static(self, path):
        fname = "index.html" if path in ("/", "") else path.lstrip("/")
        full = os.path.normpath(os.path.join(STATIC, os.path.relpath(fname, "static") if fname.startswith("static/") else fname))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            self.send_error(404)
            return
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT.get(os.path.splitext(full)[1], "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    # --- routes ------------------------------------------------------------
    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        try:
            if u.path == "/api/processes":
                return self._json(STORE.process_list())
            if u.path == "/api/guardrail":
                gr_id = q.get("id", [""])[0]
                return self._json({
                    "guardrail": STORE.guardrail(gr_id),
                    "risks": STORE.linked_risks(gr_id),
                    "history": STORE.history(gr_id),
                })
            if u.path == "/api/audit":
                return self._json(STORE.audit())
            return self._static(u.path)
        except gov.EditError as e:
            return self._json({"error": str(e)}, 404)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": repr(e)}, 500)

    def do_PUT(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path != "/api/guardrail":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        payload = json.loads(self.rfile.read(length) or b"{}")
        try:
            new = STORE.edit_guardrail(
                q.get("id", [""])[0],
                changes=payload.get("changes", {}),
                actor=payload.get("actor", "role.unknown"),
                reason=payload.get("reason", ""),
                reviewer=payload.get("reviewer", ""),
            )
            return self._json({"ok": True, "guardrail": new})
        except gov.EditError as e:
            return self._json({"ok": False, "error": str(e)}, 400)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": repr(e)}, 500)


def main():
    port = 8787
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    srv = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Continuum Governance on http://localhost:{port}")
    srv.serve_forever()


if __name__ == "__main__":
    main()
