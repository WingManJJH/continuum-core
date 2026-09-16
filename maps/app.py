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
import layout  # noqa: E402  — decorative node positions (not a model edit)
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

    def do_POST(self):
        # author / edit process STRUCTURE from the canvas — create a process, or
        # add / rename / reorder / remove a step — all through the versioned,
        # hash-chained governance write path.
        u = urlparse(self.path)
        length = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(length) or b"{}")
        actor = b.get("actor", "role.ops.support_lead")
        reason = b.get("reason", "")
        try:
            if u.path == "/api/layout":
                # decorative node positions only — NOT a model edit, so it does not
                # go through the governance store, the version chain, or the audit log.
                if b.get("op") == "reset":
                    layout.reset_process(b.get("process", ""))
                    return self._json({"ok": True, "layout": {}})
                saved = layout.save_process(b.get("process", ""), b.get("positions", {}))
                return self._json({"ok": True, "layout": saved})
            if u.path == "/api/process":
                r = STORE.add_process(b.get("code", ""), b.get("name", ""),
                                      b.get("owner", ""), actor, reason)
            elif u.path == "/api/task":
                op = b.get("op")
                if op == "edit":
                    r = STORE.edit_task(b["id"], b.get("changes", {}), actor, reason)
                elif op == "add":
                    r = STORE.add_task(b["process"], b.get("name", ""), actor, reason,
                                       after=b.get("after"))
                elif op == "move":
                    r = STORE.move_task(b["id"], b.get("dir", "up"), actor, reason or "reorder step")
                elif op == "remove":
                    r = STORE.remove_task(b["id"], actor, reason)
                elif op == "bind":
                    r = STORE.bind_agent(b["id"], actor, reason or "make step agent-run")
                elif op == "unbind":
                    r = STORE.unbind_agent(b["id"], actor, reason or "make step human-only")
                else:
                    return self._json_code({"ok": False, "error": f"unknown op {op}"}, 400)
            else:
                return self.send_error(404)
            return self._json({"ok": True, "result": r})
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
