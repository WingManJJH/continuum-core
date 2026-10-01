"""Multi-user web app, end to end over HTTP (D52). Starts the real canvas app
behind the guard on a free port, in a private models dir and directory, with
development sign-in; then the OIDC flow against a local mock identity provider.

    python3 web/test_web.py
"""
from __future__ import annotations

import base64
import copy
import hashlib
import http.client
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
for d in ("mcp_server", "governance", "maps", "web", "builder"):
    sys.path.insert(0, os.path.join(ROOT, d))
os.environ["CONTINUUM_AUTH"] = "dev"
os.environ.pop("CONTINUUM_ADMIN_EMAILS", None)

import continuum_core as cc  # noqa: E402
import storage  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail and not cond else ""))


class Client:
    def __init__(self, port, origin=True):
        self.port, self.cookies, self.origin = port, {}, origin

    def req(self, method, path, body=None, form=None, headers=None, raw=None):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        h = {"Host": f"127.0.0.1:{self.port}"}
        if self.cookies:
            h["Cookie"] = "; ".join(f"{k}={v}" for k, v in self.cookies.items())
        data = None
        if body is not None:
            data, h["Content-Type"] = json.dumps(body).encode(), "application/json"
        if form is not None:
            data, h["Content-Type"] = urllib.parse.urlencode(form).encode(), "application/x-www-form-urlencoded"
        if raw is not None:
            data = raw
        if method != "GET" and self.origin:
            h["Origin"] = f"http://127.0.0.1:{self.port}"
        h.update(headers or {})
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        txt = r.read().decode()
        for k, v in r.getheaders():
            if k.lower() == "set-cookie":
                name, val = v.split(";", 1)[0].split("=", 1)
                if "Max-Age=0" in v:
                    self.cookies.pop(name, None)
                else:
                    self.cookies[name] = val
        c.close()
        try:
            js = json.loads(txt)
        except json.JSONDecodeError:
            js = None
        return r.status, js, dict(r.getheaders()), txt

    def signin(self, email, name=""):
        return self.req("POST", "/auth/dev", form={"email": email, "name": name, "next": "/"})


def serve(handler):
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def main():
    tmp = tempfile.mkdtemp()
    saved = (cc.MODELS_DIR, storage.SYSTEM_DIR)
    cc.MODELS_DIR = os.path.join(tmp, "models")
    storage.SYSTEM_DIR = os.path.join(tmp, "_system")
    try:
        seed = json.load(open(os.path.join(ROOT, "data", "seed.json")))
        import model_import
        for slug in ("acme", "beta"):
            model_import.write_model(slug, slug.title(), seed, "Seed", "test model")
        import app as canvas
        import guard
        srv = serve(guard.protect(canvas.Handler, "canvas"))
        try:
            run(srv.server_address[1], seed)
        finally:
            srv.shutdown()
        oidc_flow(tmp)
    finally:
        cc.MODELS_DIR, storage.SYSTEM_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


def edits(slug):
    with cc.use_model(slug):
        return cc.read_log()


def run(port, seed):
    anon = Client(port)
    st, _, h, _ = anon.req("GET", "/")
    check("anonymous page view redirects to sign-in", st == 302 and h.get("Location", "").startswith("/auth/login"))
    st, js, _, _ = anon.req("GET", "/api/maps?ws=acme")
    check("anonymous API call is 401", st == 401 and js["signin"])
    st, _, _, page = anon.req("GET", "/auth/login")
    check("sign-in page is served", st == 200 and "Development sign-in" in page)
    st, _, _, _ = anon.req("GET", "/styles.css")
    check("static assets don't need a session", st == 200)

    alice, bob, carol, dave = (Client(port) for _ in range(4))
    st, _, h, _ = alice.signin("alice@example.com", "Alice")
    check("dev sign-in sets an HttpOnly session cookie", st == 303 and "cc_session" in alice.cookies
          and "HttpOnly" in h.get("Set-Cookie", ""))
    st, me, _, _ = alice.req("GET", "/api/me?ws=acme")
    check("first person becomes organization admin", me["user"]["role"] == "admin" and me["auth"] == "dev")
    for c, em in ((bob, "bob@example.com"), (carol, "carol@example.com"), (dave, "dave@example.com")):
        c.signin(em)
    st, js, _, _ = alice.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "bob@example.com",
                                                              "role": "editor", "human_role": "role.ops.support_lead"})
    check("admin grants a member with a linked role", st == 200 and js["grant"]["role"] == "editor")
    alice.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "carol@example.com", "role": "viewer"})
    st, js, _, _ = bob.req("GET", "/api/members?ws=acme")
    check("member list is admin-only", st == 403)

    # identity comes from the session, never the body
    st, js, _, _ = bob.req("POST", "/api/process/edit?ws=acme", {"id": "CO.3.2.7", "changes": {"name": "KYC (bob)"},
                                                                  "actor": "role.finance.cfo", "reason": "rename"})
    ev = edits("acme")[-1]
    check("editor can change the model", st == 200 and ev["payload"]["name"] == "KYC (bob)")
    check("a spoofed body actor is ignored; the linked role is recorded", ev["actor"]["id"] == "role.ops.support_lead")
    check("the signed-in email is stamped on the event", ev["actor"].get("user") == "bob@example.com")
    check("the edit landed in acme only", not edits("beta"))
    st, js, _, _ = carol.req("POST", "/api/process/edit?ws=acme", {"id": "CO.3.2.7", "changes": {"name": "x"}, "reason": "r"})
    check("viewer cannot change the model", st == 403 and "editor" in js["error"])
    st, js, _, _ = carol.req("GET", "/api/maps?ws=acme")
    check("viewer can read", st == 200 and any(p["name"] == "KYC (bob)" for p in js["processes"]))
    st, js, _, _ = bob.req("GET", "/api/maps?ws=beta")
    check("asking for a workspace you were not given is 403", st == 403)
    st, js, _, _ = bob.req("GET", "/api/maps")
    check("without ?ws you land in a workspace you can use", st == 200
          and any(p["name"] == "KYC (bob)" for p in js["processes"]))
    st, js, _, _ = dave.req("GET", "/api/maps")
    check("a person with no grants is refused", st == 403)
    st, js, _, _ = bob.req("POST", "/api/models", {"slug": "beta"})
    check("switching to a workspace you can't use is refused", st == 403)
    st, js, _, _ = bob.req("GET", "/api/models")
    check("model list shows only your workspaces", st == 200 and [m["slug"] for m in js["models"]] == ["acme"])

    # CSRF + JSON only
    evil = Client(port, origin=False)
    evil.cookies = dict(bob.cookies)
    st, _, _, _ = evil.req("POST", "/api/process/edit?ws=acme", {"id": "CO.3.2.7", "changes": {"name": "evil"}, "reason": "r"},
                           headers={"Origin": "https://evil.example"})
    check("cross-origin write is refused", st == 403)
    st, _, _, _ = bob.req("POST", "/api/process/edit?ws=acme", raw=b"id=CO.3.2.7",
                          headers={"Content-Type": "application/x-www-form-urlencoded"})
    check("non-JSON write is refused", st == 415)

    # concurrent editors: no lost update, no 500
    statuses, lock = [], threading.Lock()

    def edit(i):
        c = Client(port)
        c.cookies = dict(bob.cookies)
        s_, _, _, _ = c.req("POST", "/api/process/edit?ws=acme", {"id": "FN.9.3.1", "changes": {"name": f"Expense {i}"},
                                                                   "reason": f"race {i}"})
        with lock:
            statuses.append(s_)
    ts = [threading.Thread(target=edit, args=(i,)) for i in range(8)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    vers = [e["to_version"] for e in edits("acme") if e["entity_id"] == "FN.9.3.1"]
    check("8 simultaneous saves: each is saved or gets 409, never 500", set(statuses) <= {200, 409} and 200 in statuses,
          str(statuses))
    check("…and no version is written twice", len(vers) == len(set(vers)) == statuses.count(200), f"{vers} {statuses}")

    # EA modules over the API
    st, js, _, _ = bob.req("POST", "/api/ea?ws=acme", {"op": "add", "type": "Capability", "reason": "map",
                                                       "fields": {"name": "Identity verification", "level": 1,
                                                                  "process_refs": ["CO.3.2.7"]}})
    cap = (js or {}).get("result", {}).get("id")
    check("editor adds a capability", st == 200 and cap == "cap.identity_verification")
    st, js, _, _ = bob.req("GET", "/api/atlas?ws=acme")
    check("Atlas shows it with its process", st == 200 and js["atlas"][0]["processes"][0]["id"] == "CO.3.2.7")
    st, js, _, _ = bob.req("GET", f"/api/ripple?ws=acme&id={cap}")
    check("Ripple over the API", st == 200 and js["ripple"]["mode"] == "upstream")
    st, js, _, _ = bob.req("POST", "/api/ea?ws=acme", {"op": "seed_pack", "pack": "iso9001", "reason": "seed"})
    check("seed the ISO 9001 pack", st == 200 and js["result"]["added"] == 28)
    st, js, _, _ = carol.req("GET", "/api/assure?ws=acme")
    check("Assure is readable by a viewer", st == 200 and js["packs"][0]["total"] == 28)
    st, js, _, _ = carol.req("GET", "/api/vitals?ws=acme")
    check("Vitals is readable by a viewer", st == 200 and 0 <= js["score"] <= 100)
    st, js, _, _ = bob.req("POST", "/api/ea?ws=acme", {"op": "add", "type": "Capability", "fields": {"name": "x", "level": 9}})
    check("invalid record is a 400 with the reason", st == 400 and "level" in js["error"])

    # versioned import + review roles
    seed2 = copy.deepcopy(seed)
    next(p for p in seed2["Process"] if p["id"] == "CO.3.2.7")["name"] = "KYC (source)"
    next(p for p in seed2["Process"] if p["id"] == "SC.4.3.6")["name"] = "PO match (source)"
    st, js, _, _ = bob.req("POST", "/api/imports?ws=acme", {"seed": seed2, "source": "Seed", "reason": "refresh"})
    check("importing is admin-only", st == 403)
    st, js, _, _ = alice.req("POST", "/api/imports?ws=acme", {"seed": seed2, "source": "Seed", "dry": True})
    check("admin previews an import (nothing written)", st == 200 and js["plan"]["updated"] == 1
          and sorted(c["id"] for c in js["plan"]["changes"] if c["action"].startswith("stage")) == ["CO.3.2.7", "FN.9.3.1"])
    st, js, _, _ = alice.req("POST", "/api/imports?ws=acme", {"seed": seed2, "source": "Seed", "reason": "refresh"})
    check("import fast-forwards untouched records and stages edited ones", st == 200 and js["result"]["staged"] == 2
          and js["result"]["updated"] == 1)
    st, js, _, _ = carol.req("GET", "/api/maps?ws=acme")
    check("bob's edit was NOT overwritten by the import", any(p["name"] == "KYC (bob)" for p in js["processes"]))
    st, js, _, _ = bob.req("GET", "/api/staged?ws=acme")
    row = next(x for x in js["staged"] if x["id"] == "CO.3.2.7")
    sid = row["sid"]
    check("staged change shows the field diff", row["diff"] == [{"field": "name", "current": "KYC (bob)",
                                                                 "incoming": "KYC (source)"}])
    st, js, _, _ = bob.req("POST", "/api/staged?ws=acme", {"op": "accept", "sid": sid})
    check("an editor cannot accept a staged change (approver role)", st == 403)
    st, js, _, _ = alice.req("POST", "/api/staged?ws=acme", {"op": "accept", "sid": sid, "expected_version": 1})
    check("accept with a stale version is 409", st == 409 and js["conflict"])
    st, js, _, _ = alice.req("GET", "/api/imports?ws=acme")
    check("import batches list who did it", js["batches"][0]["user"] == "alice@example.com")
    st, js, _, _ = alice.req("GET", "/api/approvals?ws=acme&status=pending")
    imp = [c for c in js["approvals"] if c["op"] == "accept_import_change"]
    check("staged import changes are in the approvals inbox, with their diff", len(imp) == 2
          and any(c["import"]["diff"] and c["import"]["id"] == "CO.3.2.7" for c in imp))
    cr = next(c for c in imp if c["import"]["id"] == "CO.3.2.7")
    st, js, _, _ = bob.req("POST", "/api/approvals?ws=acme", {"op": "approve", "id": cr["id"]})
    check("an editor can't approve it in the inbox either", st == 403)
    st, js, _, _ = alice.req("POST", "/api/approvals?ws=acme", {"op": "approve", "id": cr["id"], "decision_reason": "ok"})
    st2, js2, _, _ = carol.req("GET", "/api/maps?ws=acme")
    check("approving it in the inbox takes the incoming version", st == 200 and js["cr"]["status"] == "approved"
          and any(p["name"] == "KYC (source)" for p in js2["processes"]))
    st, js, _, _ = alice.req("GET", "/api/staged?ws=acme&status=all")
    check("…and the Imports screen shows it accepted", next(x for x in js["staged"] if x["id"] == "CO.3.2.7")["status"] == "accepted")

    # review fixes (D54): members are scoped to the workspace the admin role was checked on
    erin = Client(port)
    erin.signin("erin@example.com")
    alice.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "erin@example.com", "role": "admin"})
    st, js, _, _ = erin.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "erin@example.com", "role": "admin",
                                                              "workspace": "beta"})
    check("a workspace admin can't grant access to another workspace", st == 403)
    st, js, _, _ = erin.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "erin@example.com", "role": "admin",
                                                              "workspace": "*"})
    check("…or org-wide", st == 403)
    st, js, _, _ = erin.req("POST", "/api/members?ws=acme", {"op": "signout_all", "email": "alice@example.com"})
    check("…or sign an org admin out everywhere", st == 403)
    st, js, _, _ = erin.req("GET", "/api/maps?ws=../outside")
    check("a workspace id that isn't a plain slug is refused", st == 400)
    st, js, _, _ = alice.req("POST", "/api/members?ws=acme", {"op": "grant", "email": "x@example.com", "role": "viewer",
                                                               "workspace": "../_system"})
    check("…and can't be granted", st in (400, 403))
    st, js, _, _ = erin.req("GET", "/api/maps?ws=nosuchmodel")
    check("a workspace that doesn't exist is 404", st == 404)
    st, js, _, _ = erin.req("POST", "/api/process/edit?ws=acme", raw=b"[1]", headers={"Content-Type": "application/json"})
    check("a JSON body that isn't an object is 400", st == 400)
    st, _, h, _ = Client(port).req("POST", "/auth/dev", form={"email": "zed@example.com", "next": "/\\evil.example"})
    check("no open redirect after sign-in (/\\host)", st == 303 and h.get("Location") == "/")

    # the governance app honours the approval gate too (no direct guardrail edit when approval is required)
    import importlib.util
    spec = importlib.util.spec_from_file_location("gov_app", os.path.join(ROOT, "governance", "app.py"))
    gov_app = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gov_app)
    import approval_policy
    import guard as _g
    gsrv = serve(_g.protect(gov_app.Handler, "governance"))
    try:
        gc = Client(gsrv.server_address[1])
        gc.cookies = dict(alice.cookies)
        with cc.use_model("acme"):
            approval_policy.ApprovalPolicy().set("GuardrailPolicy", "required", "role.qms.iso_advisor", "gate guardrails")
        st, js, _, _ = gc.req("PUT", "/api/guardrail?ws=acme&id=gr.CO.3.2.7", {"changes": {"escalate_if": "risk_score > 0.5"},
                                                                               "reason": "direct"})
        check("governance app refuses a direct guardrail edit when approval is required", st == 400 and "approval" in js["error"])
        st, js, _, _ = gc.req("POST", "/api/processes?ws=acme", {})
        check("POST to an app without do_POST is a clean 405 (no crash)", st == 405)
    finally:
        gsrv.shutdown()

    # round two (D57): bodies are bounded and checked before they are read
    import socket
    import time as _t

    def raw(headers, body=b""):
        sk = socket.create_connection(("127.0.0.1", port), timeout=5)
        ck = "; ".join(f"{k}={v}" for k, v in alice.cookies.items())
        sk.sendall((f"POST /api/process/edit?ws=acme HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nCookie: {ck}\r\n"
                    "Content-Type: application/json\r\n" + headers + "\r\n").encode() + body)
        t0 = _t.time()
        try:
            data = sk.recv(200).decode(errors="replace")
        except socket.timeout:
            data = ""
        sk.close()
        return data.split(" ")[1] if data.startswith("HTTP/") else "none", _t.time() - t0
    code, dt = raw("Content-Length: 1000000000\r\n")
    check("a huge Content-Length is refused at once (413), nothing read", code == "413" and dt < 2)
    check("a negative Content-Length is 400", raw("Content-Length: -1\r\n")[0] == "400")
    check("a non-numeric Content-Length is 400", raw("Content-Length: lots\r\n")[0] == "400")
    deep = b"[" * 5000 + b"]" * 5000
    check("deeply nested JSON is a clean 400", raw(f"Content-Length: {len(deep)}\r\n", deep)[0] == "400")
    st, js, _, _ = carol.req("POST", "/api/approvals?ws=acme", {"op": "propose", "target_op": "accept_import_change",
                                                                "args": {"sid": "S0002-0001"}, "reason": "x"})
    check("a viewer is refused before the body matters", st == 403)
    st, js, _, _ = alice.req("POST", "/api/approvals?ws=acme", {"op": "propose", "target_op": "accept_import_change",
                                                                "args": {"sid": "S0002-0001"}, "reason": "please reject"})
    check("nobody can hand-propose an import request", st == 400 and "import" in js["error"])

    # sessions
    alice.req("POST", "/api/members?ws=acme", {"op": "signout_all", "email": "bob@example.com"})
    st, _, _, _ = bob.req("GET", "/api/maps?ws=acme")
    check("sign out everywhere ends bob's sessions", st == 401)
    forged = Client(port)
    forged.cookies = {"cc_session": alice.cookies["cc_session"][:-3] + "abc"}
    st, _, _, _ = forged.req("GET", "/api/maps?ws=acme")
    check("a tampered session cookie is refused", st == 401)
    st, _, _, _ = alice.req("GET", "/auth/logout")
    st2, _, _, _ = alice.req("GET", "/api/maps?ws=acme")
    check("sign out clears the session", st == 303 and st2 == 401)
    with cc.use_model(None):
        log = storage.get().read_lines(os.path.join(storage.SYSTEM_DIR, "access.log.jsonl"))
    check("sign-ins and grants are in the chained access log", {"signin", "grant", "signout_all"} <= {e["kind"] for e in log}
          and cc.verify_log(os.path.join(storage.SYSTEM_DIR, "access.log.jsonl"),
                            os.path.join(storage.SYSTEM_DIR, "audit_heads.json")) == {
              "log": "access.log.jsonl", "ok": True, "count": len(log), "exists": True,
              "head": log[-1]["hash"]})


# --------------------------------------------------------------------------- OIDC
def oidc_flow(tmp):
    try:
        from cryptography.hazmat.primitives import hashes, serialization  # noqa: F401
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        check("cryptography available for the OIDC test", False)
        return
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pub = key.public_key().public_numbers()
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    jwk = {"kty": "RSA", "kid": "k1", "alg": "RS256", "n": b64(pub.n.to_bytes(256, "big")), "e": b64(pub.e.to_bytes(3, "big"))}
    state = {"claims": {}, "alg": "RS256", "bad_sig": False}

    def token(claims):
        h = b64(json.dumps({"alg": state["alg"], "kid": "k1"}).encode())
        p = b64(json.dumps(claims).encode())
        sig = key.sign(f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
        if state["bad_sig"]:
            sig = bytes(len(sig))
        return f"{h}.{p}.{b64(sig)}"

    class IdP(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _j(self, o):
            b = json.dumps(o).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            if self.path == "/.well-known/openid-configuration":
                return self._j({"issuer": base, "authorization_endpoint": base + "/authorize",
                                "token_endpoint": base + "/token", "jwks_uri": base + "/jwks"})
            if self.path == "/jwks":
                return self._j({"keys": [jwk]})
            self.send_error(404)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            form = urllib.parse.parse_qs(self.rfile.read(n).decode())
            state["last_form"] = form
            return self._j({"access_token": "a", "id_token": token(state["claims"])})

    idp = serve(IdP)
    iss = f"http://127.0.0.1:{idp.server_address[1]}"
    import auth
    import app as canvas
    import guard
    env = {"CONTINUUM_AUTH": "oidc", "CONTINUUM_OIDC_ISSUER": iss, "CONTINUUM_OIDC_CLIENT_ID": "continuum",
           "CONTINUUM_OIDC_CLIENT_SECRET": "s3cret", "CONTINUUM_OIDC_ALLOW_HTTP": "1",
           "CONTINUUM_OIDC_ALLOWED_DOMAINS": "contoso.com"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    auth._DISCOVERY.clear()
    srv = serve(guard.protect(canvas.Handler, "canvas"))
    port = srv.server_address[1]
    os.environ["CONTINUUM_PUBLIC_URL"] = f"http://127.0.0.1:{port}"
    try:
        def attempt(claims_fn, label_ok):
            c = Client(port)
            st, _, h, _ = c.req("GET", "/auth/login?next=/&go=1")
            loc = urllib.parse.urlparse(h.get("Location", ""))
            q = urllib.parse.parse_qs(loc.query)
            state["claims"] = claims_fn(q)
            st2, _, h2, page = c.req("GET", "/auth/callback?" + urllib.parse.urlencode({"code": "c0de", "state": q["state"][0]}))
            return c, q, st, st2, page

        now = int(time.time())
        good = lambda q: {"iss": iss, "aud": "continuum", "exp": now + 300, "nonce": q["nonce"][0],  # noqa: E731
                          "email": "erin@contoso.com", "name": "Erin", "sub": "erin-subject"}
        c, q, st, st2, _ = attempt(good, True)
        check("OIDC: login redirects to the IdP with PKCE (S256), state and nonce",
              st == 302 and q["code_challenge_method"] == ["S256"] and q["state"] and q["nonce"]
              and q["redirect_uri"] == [f"http://127.0.0.1:{port}/auth/callback"])
        check("OIDC: valid signed ID token signs the person in", st2 == 303 and "cc_session" in c.cookies)
        verifier = state["last_form"]["code_verifier"][0]
        check("OIDC: token request carries the PKCE verifier and client secret",
              b64(hashlib.sha256(verifier.encode()).digest()) == q["code_challenge"][0]
              and state["last_form"]["client_secret"] == ["s3cret"])
        st, me, _, _ = c.req("GET", "/api/me")
        u = auth.directory()["users"].get("erin@contoso.com", {})
        check("OIDC: the person is provisioned from the IdP claims, with no access until granted",
              st == 403 and u.get("name") == "Erin" and "access" in me["error"])
        _, _, _, st2, page = attempt(lambda q: {**good(q), "nonce": "wrong"}, False)
        check("OIDC: nonce mismatch is refused", st2 == 401 and "nonce" in page)
        _, _, _, st2, page = attempt(lambda q: {**good(q), "aud": "someone-else"}, False)
        check("OIDC: wrong audience is refused", st2 == 401 and "audience" in page)
        _, _, _, st2, page = attempt(lambda q: {**good(q), "email": "mallory@evil.com"}, False)
        check("OIDC: email outside the allowed domains is refused", st2 == 403 and "allowed" in page)
        state["bad_sig"] = True
        _, _, _, st2, page = attempt(good, False)
        check("OIDC: a bad signature is refused", st2 == 401 and "signature" in page)
        state["bad_sig"] = False
        state["alg"] = "none"
        _, _, _, st2, page = attempt(good, False)
        check("OIDC: alg=none is refused", st2 == 401)
        state["alg"] = "HS256"
        _, _, _, st2, page = attempt(good, False)
        check("OIDC: algorithms other than RS256 are refused", st2 == 401 and "RS256" in page)
        state["alg"] = "RS256"
        _, _, _, st2, page = attempt(lambda q: {**good(q), "email_verified": False}, False)
        check("OIDC: an unverified email is refused", st2 == 403 and "not verified" in page)
        _, _, _, st2, page = attempt(lambda q: {**good(q), "sub": "someone-else"}, False)
        check("OIDC: the same email from a different subject can't take the account", st2 == 403 and "bound" in page)
        c2 = Client(port)
        c2.req("GET", "/auth/login?next=/&go=1")
        st2, _, _, page = c2.req("GET", "/auth/callback?code=x&state=forged")
        check("OIDC: a forged state is refused", st2 == 400)
    finally:
        srv.shutdown()
        idp.shutdown()
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        os.environ.pop("CONTINUUM_PUBLIC_URL", None)
        os.environ["CONTINUUM_AUTH"] = "dev"


if __name__ == "__main__":
    main()
