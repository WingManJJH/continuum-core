"""Multi-user front door for every Continuum web app (D52).

`protect(Handler, app)` wraps an app's request handler. With CONTINUUM_AUTH=off it
changes nothing. Otherwise every request is:

  1. authenticated from the signed session cookie (sign-in routes under /auth/*);
  2. bound to a workspace the person may use (?ws=…, else their last choice);
  3. authorized: viewer reads, editor changes, approver decides reviews, admin
     manages members / policy / imports;
  4. stripped of any client-supplied identity: actor / reviewer / proposed_by in
     the body are replaced by the person's governed actor;
  5. run inside cc.use_model(workspace, user), so the app reads and writes that
     workspace only and the signed-in email is stamped on every event.
State-changing requests must be JSON and same-origin (CSRF).
"""
from __future__ import annotations

import html
import io
import json
import os
import sys
from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlencode, urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import auth  # noqa: E402
import continuum_core as cc  # noqa: E402

PUBLIC = ("/portal.html", "/portal.js", "/styles.css", "/favicon.ico", "/api/portal/view")
IDENTITY_FIELDS = ("actor", "reviewer", "proposed_by")

# (app, method, path) -> extra rule: function(body) -> minimum role. Default: GET viewer, writes editor.
ADMIN_PATHS = {"/api/approval-policy", "/api/members", "/api/imports/revert", "/api/imports", "/api/build/model"}
APPROVER_OPS = {"/api/approvals": {"approve", "reject", "assign"}, "/api/staged": {"accept", "reject"}}


def required_role(method: str, path: str, body: dict | None) -> str:
    if method in ("GET", "HEAD"):
        return "admin" if path == "/api/members" else "viewer"
    if path in ADMIN_PATHS:
        return "admin"
    ops = APPROVER_OPS.get(path)
    if ops and (body or {}).get("op") in ops:
        return "approver"
    if path == "/api/models":
        return "viewer"  # switching your own workspace view
    return "editor"


def _cookies(handler) -> dict:
    c = SimpleCookie()
    try:
        c.load(handler.headers.get("Cookie", ""))
    except Exception:  # noqa: BLE001
        return {}
    return {k: v.value for k, v in c.items()}


def _send(handler, code, body: bytes, ctype="application/json", cookies=(), location=None):
    handler.send_response(code)
    handler.send_header("Content-Type", ctype)
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    for ck in cookies:
        handler.send_header("Set-Cookie", ck)
    if location:
        handler.send_header("Location", location)
    handler.end_headers()
    if handler.command != "HEAD":
        handler.wfile.write(body)


def _json(handler, obj, code=200, cookies=()):
    _send(handler, code, json.dumps(obj).encode(), cookies=cookies)


def _page(title, inner) -> bytes:
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)} · Continuum</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14212b;--muted:#5d6b78;--line:#dfe4ea;--brand:#14425a;--accent:#1e88c1}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f161c;--card:#162129;--ink:#e6edf3;--muted:#9fb0bf;--line:#2a3742;--brand:#7cc4e8;--accent:#4fb3e8}}}}
body{{margin:0;font:15px/1.5 system-ui,-apple-system,Segoe UI,sans-serif;background:var(--bg);color:var(--ink);display:grid;place-items:center;min-height:100vh;padding:16px;box-sizing:border-box}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:32px;max-width:420px;width:100%;box-shadow:0 8px 30px rgba(0,0,0,.06)}}
h1{{margin:0 0 4px;font-size:22px;color:var(--brand)}} p{{color:var(--muted);margin:0 0 20px}}
label{{display:block;font-size:13px;color:var(--muted);margin-bottom:6px}}
input{{width:100%;box-sizing:border-box;padding:10px 12px;border:1px solid var(--line);border-radius:8px;background:transparent;color:var(--ink);font:inherit}}
.btn{{display:block;width:100%;margin-top:14px;padding:11px;border:0;border-radius:8px;background:var(--accent);color:#fff;font:600 15px system-ui;cursor:pointer;text-align:center;text-decoration:none}}
.note{{margin-top:18px;font-size:12px;color:var(--muted)}} .err{{color:#c0392b;margin-bottom:12px}}
</style></head><body><main class="card"><h1>Continuum</h1>{inner}</main></body></html>""".encode()


def _signin_page(next_url, error=""):
    err = f'<div class="err">{html.escape(error)}</div>' if error else ""
    if auth.mode() == "oidc":
        q = urlencode({"next": next_url})
        return _page("Sign in", f"""<p>Sign in with your organization account.</p>{err}
<a class="btn" href="/auth/login?{q}&go=1">Sign in with Microsoft / your identity provider</a>
<div class="note">Your access to each model is set by your Continuum administrator.</div>""")
    return _page("Sign in", f"""<p>Development sign-in. Type an email to sign in as that person.</p>{err}
<form method="post" action="/auth/dev"><input type="hidden" name="next" value="{html.escape(next_url)}">
<label for="em">Email</label><input id="em" name="email" type="email" required autofocus placeholder="you@company.com">
<label for="nm" style="margin-top:12px">Name (optional)</label><input id="nm" name="name">
<button class="btn" type="submit">Sign in</button></form>
<div class="note">CONTINUUM_AUTH=dev is for local testing. Use CONTINUUM_AUTH=oidc in production.</div>""")


def protect(Handler, app: str):
    class Guarded(Handler):
        _cc_app = app

        # ---- entry points
        def do_GET(self):
            return self._cc("GET", super().do_GET)

        def do_HEAD(self):
            return self._cc("HEAD", getattr(super(), "do_HEAD", super().do_GET))

        def do_POST(self):
            return self._cc("POST", super().do_POST)

        def do_PUT(self):
            return self._cc("PUT", getattr(super(), "do_PUT", None))

        def do_DELETE(self):
            return self._cc("DELETE", getattr(super(), "do_DELETE", None))

        # ---- the gate
        def _cc(self, method, inner):
            u = urlparse(self.path)
            if u.path.startswith("/auth/"):
                return self._auth_route(method, u)
            if auth.mode() == "off":
                if u.path == "/api/me":
                    return _json(self, {"ok": True, "auth": "off"})  # single-user: the UI keeps its role picker
                if inner is None:
                    return self.send_error(405)
                return inner()
            ck = _cookies(self)
            user = auth.user_from_session(ck.get(auth.COOKIE))
            if user is None:
                if u.path in PUBLIC or (not u.path.startswith("/api/") and u.path not in ("/", "/index.html")
                                        and "." in u.path.rsplit("/", 1)[-1]):
                    return inner() if inner else self.send_error(405)  # static assets + token-gated portal
                if u.path.startswith("/api/"):
                    return _json(self, {"ok": False, "error": "sign in required", "signin": "/auth/login"}, 401)
                return _send(self, 302, b"", "text/plain", location="/auth/login?" + urlencode({"next": self.path}))
            if method not in ("GET", "HEAD"):
                origin = self.headers.get("Origin")
                if origin and urlparse(origin).netloc != self.headers.get("Host", ""):
                    return _json(self, {"ok": False, "error": "cross-origin request refused"}, 403)
            asked = (parse_qs(u.query).get("ws") or [None])[0]
            ws = asked or ck.get(auth.WS_COOKIE) or "default"
            g = auth.access(user["email"], ws)
            if g is None and asked:
                return _json(self, {"ok": False, "error": f"you don't have access to {asked}"}, 403)
            if g is None:
                mine = auth.workspaces_for(user["email"])
                if not mine:
                    if u.path.startswith("/api/"):
                        return _json(self, {"ok": False, "error": "you have no access to any model yet — ask an administrator"}, 403)
                    return _send(self, 403, _page("No access", f"<p>Signed in as <b>{html.escape(user['email'])}</b>, "
                                 "but you have not been given access to a model yet. Ask your Continuum administrator.</p>"
                                 '<a class="btn" href="/auth/logout">Sign out</a>'), "text/html; charset=utf-8")
                ws = mine[0]
                g = auth.access(user["email"], ws)
            body = None
            if method in ("POST", "PUT", "DELETE"):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
                if raw and ctype != "application/json":
                    return _json(self, {"ok": False, "error": "requests must be JSON"}, 415)
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return _json(self, {"ok": False, "error": "invalid JSON"}, 400)
            need = required_role(method, u.path, body)
            if auth.RANK[g["role"]] < auth.RANK[need]:
                return _json(self, {"ok": False, "error": f"this needs the {need} role on {ws} (you are {g['role']})"}, 403)
            actor = auth.actor_for(user, g)
            me = {"email": user["email"], "name": user.get("name", ""), "role": g["role"], "actor": actor, "workspace": ws}
            # routes the guard owns in auth mode
            if u.path == "/api/me" and method == "GET":
                return _json(self, {"ok": True, "auth": auth.mode(), "user": me,
                                    "workspaces": [{"slug": w, "role": (auth.access(user["email"], w) or {}).get("role")}
                                                   for w in auth.workspaces_for(user["email"])]})
            if u.path == "/api/models" and method == "POST":
                slug = (body or {}).get("slug") or "default"
                if auth.access(user["email"], slug) is None:
                    return _json(self, {"ok": False, "error": f"no access to {slug}"}, 403)
                with cc.use_model(slug, me):
                    models = [dict(m, active=m["slug"] == slug) for m in cc.list_models()
                              if auth.access(user["email"], m["slug"])]
                return _json(self, {"ok": True, "active": slug, "models": models},
                             cookies=[auth.cookie_header(auth.WS_COOKIE, slug, 3600 * 24 * 365)])
            if u.path == "/api/members":
                return self._members(method, body, user, ws)
            if body is not None:
                for f in IDENTITY_FIELDS:
                    if f in body or f == "actor":
                        body[f] = actor
                raw = json.dumps(body).encode()
                self.rfile = io.BytesIO(raw)
                self.headers.replace_header("Content-Length", str(len(raw))) if "Content-Length" in self.headers \
                    else self.headers.add_header("Content-Length", str(len(raw)))
            if inner is None:
                return self.send_error(405)
            with cc.use_model(ws, me):
                if u.path == "/api/models" and method == "GET":
                    models = [dict(m, active=m["slug"] == ws) for m in cc.list_models()
                              if auth.access(user["email"], m["slug"])]
                    return _json(self, {"active": ws, "models": models})
                return inner()

        # ---- members (admin)
        def _members(self, method, body, user, ws):
            try:
                if method == "GET":
                    return _json(self, {"ok": True, "workspace": ws, "members": auth.members(ws), "roles": auth.ROLES})
                op = (body or {}).get("op")
                target_ws = (body or {}).get("workspace") or ws
                if target_ws == auth.ALL and (auth.access(user["email"], "__probe__") or {}).get("role") != "admin":
                    return _json(self, {"ok": False, "error": "only an organization admin can grant org-wide access"}, 403)
                if op == "grant":
                    g = auth.grant(user["email"], body.get("email", ""), target_ws, body.get("role", "viewer"),
                                   body.get("human_role", ""))
                elif op == "revoke":
                    auth.revoke(user["email"], body.get("email", ""), target_ws)
                    g = None
                elif op == "signout_all":
                    auth.signout_everywhere(user["email"], body.get("email", ""))
                    g = None
                else:
                    return _json(self, {"ok": False, "error": "op must be grant / revoke / signout_all"}, 400)
                return _json(self, {"ok": True, "grant": g, "members": auth.members(ws)})
            except auth.AuthError as e:
                return _json(self, {"ok": False, "error": str(e)}, e.status)

        # ---- /auth/*
        def _auth_route(self, method, u):
            q = parse_qs(u.query)
            nxt = (q.get("next") or ["/"])[0]
            try:
                if u.path == "/auth/login":
                    if auth.mode() == "off":
                        return _send(self, 302, b"", "text/plain", location="/")
                    if auth.mode() == "oidc" and q.get("go"):
                        url, ck = auth.oidc_begin(nxt)
                        return _send(self, 302, b"", "text/plain", location=url,
                                     cookies=[auth.cookie_header(auth.OIDC_COOKIE, ck, 600)])
                    return _send(self, 200, _signin_page(auth._safe_next(nxt)), "text/html; charset=utf-8")
                if u.path == "/auth/dev" and method == "POST" and auth.mode() == "dev":
                    n = int(self.headers.get("Content-Length") or 0)
                    form = parse_qs(self.rfile.read(n).decode()) if n else {}
                    if self.headers.get("Origin") and urlparse(self.headers["Origin"]).netloc != self.headers.get("Host", ""):
                        raise auth.AuthError("cross-origin sign-in refused", 403)
                    user = auth.ensure_user((form.get("email") or [""])[0], (form.get("name") or [""])[0], "dev")
                    return _send(self, 303, b"", "text/plain", location=auth._safe_next((form.get("next") or ["/"])[0]),
                                 cookies=[auth.cookie_header(auth.COOKIE, auth.new_session(user), auth.SESSION_SECONDS)])
                if u.path == "/auth/callback" and auth.mode() == "oidc":
                    if q.get("error"):
                        raise auth.AuthError(q.get("error_description", q["error"])[0], 401)
                    r = auth.oidc_finish((q.get("code") or [""])[0], (q.get("state") or [""])[0],
                                         _cookies(self).get(auth.OIDC_COOKIE))
                    return _send(self, 303, b"", "text/plain", location=r["next"],
                                 cookies=[auth.cookie_header(auth.COOKIE, auth.new_session(r["user"]), auth.SESSION_SECONDS),
                                          auth.cookie_header(auth.OIDC_COOKIE, "", 0)])
                if u.path == "/auth/logout":
                    return _send(self, 303, b"", "text/plain", location="/auth/login",
                                 cookies=[auth.cookie_header(auth.COOKIE, "", 0)])
                return self.send_error(404)
            except auth.AuthError as e:
                return _send(self, e.status, _signin_page(auth._safe_next(nxt), str(e)), "text/html; charset=utf-8")

    Guarded.__name__ = Handler.__name__
    return Guarded


def host() -> str:
    """Bind address: 127.0.0.1 unless CONTINUUM_HOST says otherwise (e.g. behind a proxy)."""
    return os.environ.get("CONTINUUM_HOST", "127.0.0.1")
