"""One web address for all five apps (D55).

    python3 web/gateway.py               # http://localhost:8080
    python3 web/gateway.py --port 9000

    /             canvas      (process canvas, Enterprise, Imports, approvals)
    /governance/  governance  (guardrail editor + audit)
    /dashboard/   dashboard   (strategy-to-execution report)
    /advisor/     advisor     (analyze anything against standards)
    /ask/         ask         (plain-English questions over the graph)
    /api/apps     the list above, for the canvas's app menu

One process, one origin: one sign-in cookie, one TLS certificate, one reverse-proxy
rule, one redirect URI for Entra ID. Each app keeps its own handler, wrapped by the
guard exactly as when it runs alone; the gateway only strips the prefix and hands
the request over, so an app behaves identically on its own port or under its prefix.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import guard  # noqa: E402

# prefix, app name, module path, title
MOUNTS = [
    ("/governance", "governance", "governance/app.py", "Governance"),
    ("/dashboard", "dashboard", "dashboard/app.py", "Dashboard"),
    ("/advisor", "advisor", "advisor/app.py", "Advisor"),
    ("/ask", "ask", "ask/app.py", "Ask"),
    ("", "canvas", "maps/app.py", "Canvas"),   # root last: longest prefix wins
]


def _load(name: str, rel: str):
    path = os.path.join(ROOT, rel)
    d = os.path.dirname(path)
    if d not in sys.path:
        sys.path.insert(0, d)
    spec = importlib.util.spec_from_file_location(f"continuum_app_{name}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_handlers() -> list[tuple[str, str, str, type]]:
    out = []
    for prefix, name, rel, title in MOUNTS:
        mod = _load(name, rel)
        out.append((prefix, name, title, guard.protect(mod.Handler, name)))
    return out


def make_gateway(handlers):
    apps = [{"name": n, "title": t, "href": (p or "") + "/"} for p, n, t, _h in handlers]

    class Gateway(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *a):
            pass

        def _route(self):
            path = urlsplit(self.path).path
            if path == "/api/apps":
                body = json.dumps({"apps": apps}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return None
            for prefix, _name, _title, H in handlers:
                if not prefix:
                    return H, ""
                if path == prefix:                       # /governance -> /governance/
                    q = self.path[len(prefix):]
                    self.send_response(301)
                    self.send_header("Location", prefix + "/" + q)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return None
                if path.startswith(prefix + "/"):
                    return H, prefix
            return None

        def _dispatch(self, method):
            hit = self._route()
            if hit is None:
                return
            H, prefix = hit
            self.cc_prefix = prefix
            self.path = self.path[len(prefix):] or "/"
            self.__class__ = H                           # same socket, same request: the app's own handler
            fn = getattr(self, "do_" + method, None)
            if fn is None:
                return self.send_error(405)
            return fn()

        def do_GET(self):
            self._dispatch("GET")

        def do_HEAD(self):
            self._dispatch("HEAD")

        def do_POST(self):
            self._dispatch("POST")

        def do_PUT(self):
            self._dispatch("PUT")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Gateway


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    port = int(os.environ.get("CONTINUUM_PORT", "8080"))
    if "--port" in argv:
        port = int(argv[argv.index("--port") + 1])
    srv = ThreadingHTTPServer((guard.host(), port), make_gateway(build_handlers()))
    print(f"Continuum on http://localhost:{port}  ·  /governance/ /dashboard/ /advisor/ /ask/")
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
