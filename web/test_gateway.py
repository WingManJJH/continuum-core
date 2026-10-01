"""One web address for all five apps (D55), over real HTTP with sign-in on.

    python3 web/test_gateway.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
for d in ("mcp_server", "governance", "maps", "web", "builder"):
    sys.path.insert(0, os.path.join(ROOT, d))
os.environ["CONTINUUM_AUTH"] = "dev"
os.environ.pop("CONTINUUM_ADMIN_EMAILS", None)

import continuum_core as cc  # noqa: E402
import storage  # noqa: E402
from test_web import Client  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def main():
    tmp = tempfile.mkdtemp()
    saved = (cc.MODELS_DIR, storage.SYSTEM_DIR)
    cc.MODELS_DIR, storage.SYSTEM_DIR = os.path.join(tmp, "models"), os.path.join(tmp, "_system")
    try:
        import model_import
        model_import.write_model("acme", "Acme", json.load(open(os.path.join(ROOT, "data", "seed.json"))), "Seed", "t")
        import gateway
        srv = ThreadingHTTPServer(("127.0.0.1", 0), gateway.make_gateway(gateway.build_handlers()))
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            run(srv.server_address[1])
        finally:
            srv.shutdown()
    finally:
        cc.MODELS_DIR, storage.SYSTEM_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)
    startup_fails_fast()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


def startup_fails_fast():
    """D59: an unreachable or refused database stops startup in one line, quickly."""
    import subprocess
    import time
    env = dict(os.environ, CONTINUUM_DATABASE_URL="postgresql://nobody@127.0.0.1:1/none?connect_timeout=2")
    env.pop("PGPASSWORD", None)
    t0 = time.time()
    r = subprocess.run([sys.executable, os.path.join(ROOT, "web", "gateway.py"), "--port", "0"],
                       env=env, capture_output=True, text=True, timeout=60)
    check("a bad database login stops startup with exit 1, in seconds",
          r.returncode == 1 and time.time() - t0 < 20, f"rc={r.returncode} {time.time() - t0:.1f}s")
    check("…with one clear line, not a traceback",
          r.stderr.startswith("Continuum did not start: cannot connect to Postgres") and "Traceback" not in r.stderr,
          r.stderr[-300:])


def run(port):
    anon = Client(port)
    st, js, _, _ = anon.req("GET", "/api/apps")
    check("the app list is served", st == 200 and [a["href"] for a in js["apps"]][-1] == "/"
          and {a["name"] for a in js["apps"]} == {"canvas", "governance", "dashboard", "advisor", "ask"})
    st, _, h, _ = anon.req("GET", "/governance/")
    check("an app page without a session goes to sign-in and comes back to that app",
          st == 302 and "next=%2Fgovernance%2F" in h.get("Location", ""))
    st, _, h, _ = anon.req("GET", "/governance")
    check("/governance redirects to /governance/", st == 301 and h.get("Location") == "/governance/")

    u = Client(port)
    st, _, h, _ = u.req("POST", "/auth/dev", form={"email": "ann@example.com", "next": "/governance/"})
    check("one sign-in, then straight back to the app asked for", st == 303 and h.get("Location") == "/governance/")
    for path, needle in (("/", "Process Canvas"), ("/governance/", "Governance"), ("/dashboard/", "Strategy"),
                         ("/advisor/", "Advisor"), ("/ask/", "Ask the Agent")):
        st, _, _, page = u.req("GET", path)
        check(f"{path} serves its own app", st == 200 and needle in page)
    st, _, _, css = u.req("GET", "/governance/styles.css")
    st2, _, _, css2 = u.req("GET", "/styles.css")
    check("each app keeps its own static files", st == st2 == 200 and css != css2)
    checks = [("/api/maps?ws=acme", "processes"), ("/governance/api/processes?ws=acme", None),
              ("/dashboard/api/rollup?ws=acme", None), ("/advisor/api/subjects?ws=acme", None),
              ("/ask/api/examples?ws=acme", None)]
    for path, key in checks:
        st, js, _, _ = u.req("GET", path)
        check(f"{path.split('?')[0]} answers through the one address with the one session",
              st == 200 and js is not None and (key is None or key in js), f"{st}")
    st, js, _, _ = u.req("GET", "/governance/api/guardrail?ws=acme&id=gr.CO.3.2.7")
    check("same path in two apps stays separate (/governance/api/guardrail)", st == 200 and js["guardrail"]["id"] == "gr.CO.3.2.7")
    st, _, _, _ = u.req("GET", "/nowhere/")
    check("an unknown path falls to the canvas (404 there)", st == 404)
    st, js, _, _ = u.req("PUT", "/governance/api/guardrail?ws=acme&id=gr.CO.3.2.7",
                         {"changes": {"escalate_if": "risk_score > 0.8"}, "reason": "via gateway", "actor": "role.finance.cfo",
                          "reviewer": "role.finance.cfo"})
    with cc.use_model("acme"):
        log = cc.read_log()
    ev = log[-1] if log else {"actor": {}}
    check("writes through a prefix keep identity from the session", st == 200 and ev["actor"]["user"] == "ann@example.com"
          and ev["actor"]["id"] != "role.finance.cfo")


if __name__ == "__main__":
    main()
