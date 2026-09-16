"""
Publish portal (Phase E of the visual modeler).

Turns any process — or the whole process landscape — into a **read-only,
shareable viewer** addressed by an unguessable token. A process owner mints a
share link from the canvas; whoever holds the link sees a clean, read-only
rendering (flow, lanes, RACI, checklist, guardrails) with no authoring controls.

Like the layout layer, this is **operational state, not governed model data**
(Core Model §08): minting or revoking a share link is not a process edit, so it
never goes through the versioned / hash-chained governance write path and never
changes what an agent reads. It lives in data/portal.json.

The view it serves is **live**: the portal reads the current graph every time, so
a shared link always shows today's model — and it reports whether the model has
changed since the link was minted (`current`), so a viewer knows if what they see
differs from what the author shared.

Honest boundary: a token is an unguessable *capability URL* served on the same
host — it is not viewer authentication. Genuine external publishing (a public
URL, per-viewer sign-in, server-enforced access) is a deployment step, declared
like the connector OAuth seams. What is real here and now: minting, listing,
revocation, and time-boxed expiry are all enforced below.

    { "<token>": {token, target, title, created_by, created_at,
                  expires_at|null, model_sig, revoked}, ... }
"""
from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
import sys

sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
from mapdata import all_maps, landscape  # noqa: E402

PORTAL_PATH = os.path.normpath(os.path.join(HERE, "..", "data", "portal.json"))
LANDSCAPE_TARGET = "__landscape__"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _load_all() -> dict:
    try:
        with open(PORTAL_PATH) as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_all(data: dict) -> None:
    os.makedirs(os.path.dirname(PORTAL_PATH), exist_ok=True)
    with open(PORTAL_PATH, "w") as f:
        json.dump(data, f, indent=2)


def _expired(rec: dict, now: datetime | None = None) -> bool:
    exp = rec.get("expires_at")
    if not exp:
        return False
    try:
        return _parse(exp) <= (now or _now())
    except (ValueError, TypeError):
        return False


def _parse(iso: str) -> datetime:
    dt = datetime.fromisoformat(iso)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _target_name(target: str, g: cc.Graph) -> str:
    if target == LANDSCAPE_TARGET:
        return "Whole process landscape"
    p = g.get("Process", target)
    return p["name"] if p else target


def publish(target: str, title: str, created_by: str, *,
            g: cc.Graph | None = None, ttl_days: int | None = None,
            expires_at: str | None = None) -> dict:
    """Mint a read-only share link for a process id (or the landscape) and return
    the stored record (including its `token`). Refuses an unknown target — you
    can't share a link to something that isn't in the model."""
    g = g or cc.Graph()
    if target != LANDSCAPE_TARGET and g.get("Process", target) is None:
        raise ValueError(f"unknown process {target}")
    if not (created_by or "").startswith("role."):
        raise ValueError("a share link must be attributed to a role")
    if expires_at is None and ttl_days:
        from datetime import timedelta
        expires_at = (_now() + timedelta(days=int(ttl_days))).isoformat()
    token = secrets.token_urlsafe(9)
    rec = {
        "token": token,
        "target": target,
        "title": (title or "").strip() or _target_name(target, g),
        "created_by": created_by,
        "created_at": _now().isoformat(),
        "expires_at": expires_at,
        "model_sig": g.model_sig,
        "revoked": False,
    }
    allp = _load_all()
    allp[token] = rec
    _save_all(allp)
    return rec


def get(token: str, now: datetime | None = None) -> dict | None:
    """Return a live (not revoked, not expired) share record, or None."""
    rec = _load_all().get(token or "")
    if rec is None or rec.get("revoked") or _expired(rec, now):
        return None
    return rec


def revoke(token: str) -> bool:
    """Turn a share link off. Idempotent; returns True if a link was revoked."""
    allp = _load_all()
    rec = allp.get(token or "")
    if rec is None or rec.get("revoked"):
        return False
    rec["revoked"] = True
    rec["revoked_at"] = _now().isoformat()
    _save_all(allp)
    return True


def _status(rec: dict, now: datetime | None = None) -> str:
    if rec.get("revoked"):
        return "revoked"
    if _expired(rec, now):
        return "expired"
    return "active"


def all_links(g: cc.Graph | None = None) -> list[dict]:
    """Every minted link, newest first, annotated for the author's manage list:
    live status, human target name, and whether the model still matches what was
    shared (`current`)."""
    g = g or cc.Graph()
    out = []
    for rec in _load_all().values():
        out.append({
            "token": rec["token"],
            "target": rec["target"],
            "target_name": _target_name(rec["target"], g),
            "title": rec.get("title", ""),
            "created_by": rec.get("created_by", ""),
            "created_at": rec.get("created_at", ""),
            "expires_at": rec.get("expires_at"),
            "status": _status(rec),
            "current": rec.get("model_sig") == g.model_sig,
        })
    return sorted(out, key=lambda r: r.get("created_at", ""), reverse=True)


def portal_view(token: str, g: cc.Graph | None = None,
                now: datetime | None = None) -> dict | None:
    """Resolve a token to the read-only payload the viewer renders. Returns None
    for an unknown / revoked / expired token. The payload is a pure read of the
    current graph — no write verbs, no edit affordances."""
    rec = get(token, now)
    if rec is None:
        return None
    g = g or cc.Graph()
    meta = {
        "title": rec.get("title", ""),
        "target": rec["target"],
        "published_at": rec.get("created_at", ""),
        "published_by": rec.get("created_by", ""),
        "model_sig": g.model_sig,
        "current": rec.get("model_sig") == g.model_sig,
        "generated_at": (now or _now()).isoformat(),
    }
    if rec["target"] == LANDSCAPE_TARGET:
        return {"kind": "landscape", "meta": meta, "landscape": landscape(g)}
    proc = next((m for m in all_maps(g) if m["id"] == rec["target"]), None)
    if proc is None:  # process was retired after the link was minted
        return {"kind": "gone", "meta": meta}
    return {"kind": "process", "meta": meta, "process": proc}


if __name__ == "__main__":
    r = publish("CO.3.2.7", "Customer onboarding", "role.ops.support_lead")
    print("minted:", r["token"])
    print(json.dumps(portal_view(r["token"])["meta"], indent=2))
    revoke(r["token"])
    print("after revoke, get():", get(r["token"]))
