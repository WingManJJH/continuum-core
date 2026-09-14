"""
Advisor — the in-app AI window that analyzes any subject against best practices &
standards. Pick a process / guardrail / task / the whole model, or paste content or
data, and get a scored analysis with findings that cite the standard each comes from.

Backed by the deterministic RulesAdvisor (no model access needed); the LLMAdvisor
seam is where a live model plugs in once auth exists.

    python3 app.py            # http://localhost:8790
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
from advisor import RulesAdvisor  # noqa: E402

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
        if u.path == "/api/subjects":
            g = cc.Graph()
            return self._json({
                "process": [{"id": p["id"], "name": p["name"]}
                            for p in sorted(g.all("Process"), key=lambda x: x["id"]) if p["status"] == "active"],
                "guardrail": [{"id": gr["id"], "name": gr["id"] + " v" + str(gr["version"])}
                              for gr in sorted(g.all("GuardrailPolicy"), key=lambda x: x["id"]) if gr["status"] == "active"],
                "task": [{"id": t["id"], "name": t["name"]}
                         for t in sorted(g.all("Task"), key=lambda x: x["id"]) if t["status"] == "active"],
            })
        return self._static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        if u.path != "/api/analyze":
            return self.send_error(404)
        length = int(self.headers.get("Content-Length", 0))
        b = json.loads(self.rfile.read(length) or b"{}")
        try:
            r = RulesAdvisor().analyze(b.get("subject_type", ""), b.get("id", ""), b.get("content", ""))
            code = 200 if "error" not in r else 400
            return self._json(r, code)
        except Exception as e:  # noqa: BLE001
            return self._json({"error": repr(e)}, 500)


def main():
    port = 8790
    if "--port" in sys.argv:
        port = int(sys.argv[sys.argv.index("--port") + 1])
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    print("Continuum Advisor on http://localhost:8790")
    main()
