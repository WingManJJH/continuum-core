"""Sign-in, sessions, roles and workspace membership for the multi-user apps (D52).

Modes (CONTINUUM_AUTH):
  off   — single-user, as before (default, so existing local use is unchanged)
  dev   — development sign-in: type an email; for local multi-user testing only
  oidc  — OpenID Connect (Microsoft Entra ID first; any OIDC issuer by config)

Identity is taken ONLY from the signed session — never from a request body.

Access is per workspace (one governed model): viewer < editor < approver < admin.
A membership may link the person to a model HumanRole, which becomes the actor on
every governed change they make (the model is role-based, ISO 9001 §5.3); the
signed-in email is recorded alongside it on every event.

Everything is stored through `storage` (files or Postgres), in the system space:
  _system/access.log.jsonl — chained: users, grants, revokes, sign-ins, sign-out-everywhere
  _system/secret.json      — session-signing key when CONTINUUM_SECRET_KEY is not set

OIDC: authorization-code flow with PKCE, state and nonce. The ID token comes
straight from the token endpoint over TLS (OIDC Core §3.1.3.7); its RS256 signature
is also verified against the issuer's JWKS, and iss / aud / exp / nonce are checked.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import storage  # noqa: E402

ROLES = ("viewer", "editor", "approver", "admin")
RANK = {r: i for i, r in enumerate(ROLES, 1)}
ALL = "*"                       # a grant on every workspace (organization admin)
COOKIE = "cc_session"
WS_COOKIE = "cc_ws"
OIDC_COOKIE = "cc_oidc"
SESSION_SECONDS = int(os.environ.get("CONTINUUM_SESSION_HOURS", "12")) * 3600
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class AuthError(PermissionError):
    def __init__(self, msg, status=403):
        super().__init__(msg)
        self.status = status


def mode() -> str:
    m = os.environ.get("CONTINUUM_AUTH", "off").strip().lower()
    return m if m in ("off", "dev", "oidc") else "off"


def system_dir() -> str:
    return storage.SYSTEM_DIR


def _log_path() -> str:
    return os.path.join(system_dir(), "access.log.jsonl")


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


# --------------------------------------------------------------------------- directory
def _events() -> list[dict]:
    return storage.get().read_lines(_log_path())


def _append(kind: str, by: str, **fields) -> dict:
    ev = {"event_id": "acc_" + cc._ulidish(), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
          "kind": kind, "by": by, **fields}
    return storage.get().append_chained(_log_path(), ev, os.path.join(system_dir(), "audit_heads.json"))


_DIR_CACHE: dict = {}


def directory() -> dict:
    """Fold the access log: {"users": {email: {...}}, "grants": {(email, ws): {...}}}.
    Cached per log length, so a request costs one size check, not a full fold."""
    key = (_log_path(), storage.get().size(_log_path()))
    hit = _DIR_CACHE.get("v")
    if hit and hit[0] == key:
        return hit[1]
    users, grants = {}, {}
    for e in _events():
        k = e["kind"]
        em = e.get("email", "").lower()
        if k == "user":
            u = users.setdefault(em, {"email": em, "name": "", "epoch": 0, "disabled": False, "created": e["ts"]})
            u.update({x: e[x] for x in ("name", "disabled") if x in e})
        elif k == "grant":
            grants[(em, e["workspace"])] = {"email": em, "workspace": e["workspace"], "role": e["role"],
                                           "human_role": e.get("human_role") or "", "by": e["by"], "at": e["ts"]}
        elif k == "revoke":
            grants.pop((em, e["workspace"]), None)
        elif k == "signout_all" and em in users:
            users[em]["epoch"] += 1
        elif k == "signin" and em in users:
            users[em]["last_signin"] = e["ts"]
    out = {"users": users, "grants": grants}
    _DIR_CACHE["v"] = (key, out)
    return out


def _admin_emails() -> set[str]:
    return {x.strip().lower() for x in os.environ.get("CONTINUUM_ADMIN_EMAILS", "").split(",") if x.strip()}


def ensure_user(email: str, name: str = "", method: str = "") -> dict:
    """Provision on first sign-in. The very first person in an empty directory (or
    anyone in CONTINUUM_ADMIN_EMAILS) becomes organization admin."""
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise AuthError("a valid email is required", 400)
    d = directory()
    u = d["users"].get(email)
    if u and u.get("disabled"):
        raise AuthError("this account is disabled — ask an administrator", 403)
    if not u:
        _append("user", "system", email=email, name=name or email.split("@")[0])
        first = not d["users"]
        if first or email in _admin_emails():
            _append("grant", "system", email=email, workspace=ALL, role="admin",
                    reason="first user" if first else "CONTINUUM_ADMIN_EMAILS")
    elif name and name != u.get("name"):
        _append("user", "system", email=email, name=name)
    _append("signin", email, email=email, method=method or mode())
    return directory()["users"][email]


def access(email: str, workspace: str) -> dict | None:
    """The person's effective grant on a workspace (org-wide admin applies everywhere)."""
    d = directory()
    g = d["grants"].get((email, workspace))
    org = d["grants"].get((email, ALL))
    if email in _admin_emails():
        org = {"role": "admin", "human_role": "", "workspace": ALL}
    if org and (not g or RANK[org["role"]] > RANK[g["role"]]):
        return {**org, "human_role": (g or {}).get("human_role", "") or org.get("human_role", ""), "workspace": workspace}
    return g


def workspaces_for(email: str) -> list[str]:
    d = directory()
    if access(email, "__probe__"):  # org-wide grant
        return ["default"] + [m["slug"] for m in cc.list_models() if m["slug"] != "default"]
    return sorted({ws for (em, ws) in d["grants"] if em == email and ws != ALL})


def grant(by: str, email: str, workspace: str, role: str, human_role: str = "") -> dict:
    if role not in ROLES:
        raise AuthError(f"role must be one of {', '.join(ROLES)}", 400)
    email = email.strip().lower()
    if not EMAIL.match(email):
        raise AuthError("a valid email is required", 400)
    if human_role and not re.match(r"^role\.[a-z0-9_.]+$", human_role):
        raise AuthError("a linked role looks like role.dept.name", 400)
    if not directory()["users"].get(email):
        _append("user", by, email=email, name=email.split("@")[0], invited=True)
    _append("grant", by, email=email, workspace=workspace, role=role, human_role=human_role)
    return access(email, workspace)


def revoke(by: str, email: str, workspace: str) -> None:
    email = email.strip().lower()
    if email == by and workspace in (ALL,):
        raise AuthError("you can't remove your own organization admin access", 400)
    _append("revoke", by, email=email, workspace=workspace)


def members(workspace: str) -> list[dict]:
    d = directory()
    out = []
    for (em, ws), g in sorted(d["grants"].items()):
        if ws in (workspace, ALL):
            u = d["users"].get(em, {})
            out.append({**g, "name": u.get("name", ""), "last_signin": u.get("last_signin"), "org_wide": ws == ALL})
    return out


def signout_everywhere(by: str, email: str) -> None:
    _append("signout_all", by, email=email.strip().lower())


def actor_for(user: dict, grant_: dict | None) -> str:
    """The governed actor id for a person: their linked HumanRole, else a stable
    member role id derived from their email (still a role id, as the model requires)."""
    if grant_ and grant_.get("human_role"):
        return grant_["human_role"]
    local = re.sub(r"[^a-z0-9]+", "_", user["email"].split("@")[0].lower()).strip("_") or "user"
    dom = re.sub(r"[^a-z0-9]+", "_", user["email"].split("@")[1].split(".")[0].lower())
    return f"role.member.{dom}.{local}"


# --------------------------------------------------------------------------- sessions
def _secret() -> bytes:
    env = os.environ.get("CONTINUUM_SECRET_KEY")
    if env:
        return env.encode()
    path = os.path.join(system_dir(), "secret.json")
    doc = storage.get().read_json(path, None)
    if not doc:
        storage.get().write_json(path, {"key": secrets.token_urlsafe(48), "note": "set CONTINUUM_SECRET_KEY in production"})
        doc = storage.get().read_json(path, None)
    return doc["key"].encode()


def sign(payload: dict) -> str:
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    return body + "." + sig


def unsign(token: str | None) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    good = _b64(hmac.new(_secret(), body.encode(), hashlib.sha256).digest())
    if not hmac.compare_digest(sig, good):
        return None
    try:
        p = json.loads(_unb64(body))
    except (ValueError, json.JSONDecodeError):
        return None
    if p.get("x", 0) < time.time():
        return None
    return p


def new_session(user: dict) -> str:
    return sign({"e": user["email"], "n": user.get("epoch", 0), "x": int(time.time()) + SESSION_SECONDS,
                 "s": secrets.token_urlsafe(8)})


def user_from_session(token: str | None) -> dict | None:
    p = unsign(token)
    if not p:
        return None
    u = directory()["users"].get(p.get("e", ""))
    if not u or u.get("disabled") or u.get("epoch", 0) != p.get("n"):
        return None   # unknown, disabled, or signed out everywhere since this session began
    return u


def cookie_header(name: str, value: str, max_age: int | None = None) -> str:
    secure = os.environ.get("CONTINUUM_PUBLIC_URL", "").startswith("https://")
    parts = [f"{name}={value}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if max_age is not None:
        parts.append(f"Max-Age={max_age}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


# --------------------------------------------------------------------------- OIDC
_DISCOVERY: dict = {}


def oidc_config() -> dict:
    iss = os.environ.get("CONTINUUM_OIDC_ISSUER", "").rstrip("/")
    if not iss:
        raise AuthError("CONTINUUM_OIDC_ISSUER is not set", 500)
    if not iss.startswith("https://") and os.environ.get("CONTINUUM_OIDC_ALLOW_HTTP") != "1":
        raise AuthError("the OIDC issuer must use https", 500)
    if iss not in _DISCOVERY:
        with urllib.request.urlopen(iss + "/.well-known/openid-configuration", timeout=10) as r:  # nosec - configured issuer
            _DISCOVERY[iss] = json.load(r)
    return _DISCOVERY[iss]


def public_url() -> str:
    return os.environ.get("CONTINUUM_PUBLIC_URL", "http://localhost:8789").rstrip("/")


def oidc_begin(next_url: str) -> tuple[str, str]:
    """Returns (authorize URL, signed state cookie value)."""
    cfg = oidc_config()
    verifier = secrets.token_urlsafe(48)
    state, nonce = secrets.token_urlsafe(16), secrets.token_urlsafe(16)
    challenge = _b64(hashlib.sha256(verifier.encode()).digest())
    q = {"response_type": "code", "client_id": os.environ["CONTINUUM_OIDC_CLIENT_ID"],
         "redirect_uri": public_url() + "/auth/callback",
         "scope": os.environ.get("CONTINUUM_OIDC_SCOPES", "openid email profile"),
         "state": state, "nonce": nonce, "code_challenge": challenge, "code_challenge_method": "S256"}
    cookie = sign({"st": state, "no": nonce, "v": verifier, "nx": _safe_next(next_url), "x": int(time.time()) + 600})
    return cfg["authorization_endpoint"] + "?" + urllib.parse.urlencode(q), cookie


def _safe_next(n: str | None) -> str:
    n = n or "/"
    return n if n.startswith("/") and not n.startswith("//") else "/"


def _verify_rs256(id_token: str, cfg: dict) -> None:
    head = json.loads(_unb64(id_token.split(".")[0]))
    if head.get("alg") == "none":
        raise AuthError("unsigned ID token refused", 401)
    if head.get("alg") != "RS256" or not cfg.get("jwks_uri"):
        return  # other algs: rely on TLS from the token endpoint (OIDC Core §3.1.3.7)
    try:
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import padding, rsa
    except ImportError:
        return
    with urllib.request.urlopen(cfg["jwks_uri"], timeout=10) as r:  # nosec - issuer's JWKS
        keys = json.load(r).get("keys", [])
    key = next((k for k in keys if k.get("kid") == head.get("kid")), None) or (keys[0] if len(keys) == 1 else None)
    if not key:
        raise AuthError("ID token signing key not found", 401)
    pub = rsa.RSAPublicNumbers(int.from_bytes(_unb64(key["e"]), "big"), int.from_bytes(_unb64(key["n"]), "big")).public_key()
    h, p, s = id_token.split(".")
    try:
        pub.verify(_unb64(s), f"{h}.{p}".encode(), padding.PKCS1v15(), hashes.SHA256())
    except Exception:  # noqa: BLE001
        raise AuthError("ID token signature is invalid", 401) from None


def oidc_finish(code: str, state: str, cookie_val: str | None) -> dict:
    st = unsign(cookie_val)
    if not st or not state or not hmac.compare_digest(st.get("st", ""), state):
        raise AuthError("sign-in expired or was tampered with — try again", 400)
    cfg = oidc_config()
    form = {"grant_type": "authorization_code", "code": code, "redirect_uri": public_url() + "/auth/callback",
            "client_id": os.environ["CONTINUUM_OIDC_CLIENT_ID"], "code_verifier": st["v"]}
    if os.environ.get("CONTINUUM_OIDC_CLIENT_SECRET"):
        form["client_secret"] = os.environ["CONTINUUM_OIDC_CLIENT_SECRET"]
    req = urllib.request.Request(cfg["token_endpoint"], data=urllib.parse.urlencode(form).encode(),
                                 headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:  # nosec - configured token endpoint
        tok = json.load(r)
    idt = tok.get("id_token")
    if not idt or idt.count(".") != 2:
        raise AuthError("the identity provider returned no ID token", 401)
    _verify_rs256(idt, cfg)
    claims = json.loads(_unb64(idt.split(".")[1]))
    iss = os.environ.get("CONTINUUM_OIDC_ISSUER", "").rstrip("/")
    aud = claims.get("aud")
    auds = aud if isinstance(aud, list) else [aud]
    if claims.get("iss", "").rstrip("/") != cfg.get("issuer", iss).rstrip("/"):
        raise AuthError("ID token issuer mismatch", 401)
    if os.environ["CONTINUUM_OIDC_CLIENT_ID"] not in auds:
        raise AuthError("ID token audience mismatch", 401)
    if claims.get("exp", 0) < time.time() - 60:
        raise AuthError("ID token expired", 401)
    if claims.get("nonce") != st.get("no"):
        raise AuthError("ID token nonce mismatch", 401)
    email = (claims.get("email") or claims.get("preferred_username") or claims.get("upn") or "").lower()
    allowed = [d.strip().lower() for d in os.environ.get("CONTINUUM_OIDC_ALLOWED_DOMAINS", "").split(",") if d.strip()]
    if allowed and email.split("@")[-1] not in allowed:
        raise AuthError(f"{email} is not in an allowed sign-in domain", 403)
    user = ensure_user(email, claims.get("name", ""), method="oidc")
    return {"user": user, "next": st.get("nx", "/")}
