"""Browser end-to-end for the multi-user canvas (D52). Starts the canvas behind the
guard (dev sign-in) in a private models dir, then drives two real browser users
with Playwright (node, from studio/test/node_modules). Also checks single-user
mode still renders. Group 'studio' in tests/run_all.py (needs node + playwright).

    python3 web/test_browser.py [--shots DIR]
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
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

NODE_MODULES = os.path.join(ROOT, "studio", "test", "node_modules")


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    shots = None
    if "--shots" in sys.argv:
        shots = os.path.abspath(sys.argv[sys.argv.index("--shots") + 1])
        os.makedirs(shots, exist_ok=True)
    tmp = tempfile.mkdtemp()
    saved = (cc.MODELS_DIR, storage.SYSTEM_DIR)
    cc.MODELS_DIR = os.path.join(tmp, "models")
    storage.SYSTEM_DIR = os.path.join(tmp, "_system")
    code = 1
    try:
        seed = json.load(open(os.path.join(ROOT, "data", "seed.json")))
        import model_import
        model_import.write_model("acme", "Acme Corp", seed, "Seed", "browser test model")
        import app as canvas
        import guard
        import versioned_import as vi
        srv = serve(guard.protect(canvas.Handler, "canvas"))
        port = srv.server_address[1]

        # a staged import waiting for review, so the review screen has content
        def stage_import():
            with cc.use_model("acme", {"email": "seed@example.com"}):
                import store as gov
                gov.GovernanceStore().edit_process("SC.4.3.6", {"name": "Match POs — our wording"},
                                                   "role.ops.head_of_operations", "local wording")
            s2 = copy.deepcopy(seed)
            next(p for p in s2["Process"] if p["id"] == "SC.4.3.6")["name"] = "Match purchase orders (vendor)"
            vi.import_model("acme", "Acme Corp", s2, "Seed", actor="role.import.service", reason="nightly sync")
        stage_import()

        env = dict(os.environ, NODE_PATH=NODE_MODULES, CC_PORT=str(port), CC_SHOTS=shots or "")
        r = subprocess.run(["node", os.path.join(HERE, "browser.e2e.js")], env=env, capture_output=True, text=True, timeout=600)
        print(r.stdout + r.stderr)
        code = r.returncode
        # the same build in single-user mode (CONTINUUM_AUTH=off) still behaves as before
        os.environ["CONTINUUM_AUTH"] = "off"
        r2 = subprocess.run(["node", os.path.join(HERE, "browser.e2e.js")], env=dict(env, CC_MODE="off", CONTINUUM_AUTH="off"),
                            capture_output=True, text=True, timeout=300)
        print(r2.stdout + r2.stderr)
        code = code or r2.returncode
        import re
        tot = [sum(int(m[i]) for m in re.findall(r"(\d+) passed, (\d+) failed", r.stdout + r2.stdout)) for i in (0, 1)]
        print(f"\n{tot[0]} passed, {tot[1]} failed")
        os.environ["CONTINUUM_AUTH"] = "dev"
        srv.shutdown()
    finally:
        cc.MODELS_DIR, storage.SYSTEM_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)
    sys.exit(code)


if __name__ == "__main__":
    main()
