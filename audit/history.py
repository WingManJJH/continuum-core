"""
Model version history & compare (version control view).

Every governed change is already a versioned, hash-chained event carrying a full
snapshot of the entity (Core Model §07 / ISO 9001 §7.5). This module reads that
change-control log and turns it into what a management team needs to see: who
changed what, when, and why — and a field-level **diff between two versions** of
any entity, or a **model-level change summary** since the seed baseline.

Read-only. It reconstructs from the audit trail; it never writes.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402


def _events(log_path: str | None = None) -> list[dict]:
    path = log_path or cc.EDITS_LOG
    out = []
    if not os.path.exists(path):
        return out
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _actor(ev: dict) -> str:
    a = ev.get("actor")
    return a.get("id", "") if isinstance(a, dict) else str(a or "")


def _diff(old: dict | None, new: dict | None) -> list[dict]:
    """Field-level diff between two entity snapshots."""
    old = old or {}
    new = new or {}
    fields = sorted(set(old) | set(new))
    changes = []
    for f in fields:
        if f in ("version",):
            continue
        a, b = old.get(f), new.get(f)
        if a != b:
            changes.append({"field": f, "old": a, "new": b})
    return changes


def entity_history(entity_type: str, entity_id: str, log_path: str | None = None) -> dict:
    """Full version timeline for one entity, with the field diff at each step."""
    evs = [e for e in _events(log_path) if e.get("entity_type") == entity_type and e.get("entity_id") == entity_id]
    timeline, prev = [], None
    for e in evs:
        payload = e.get("payload") or {}
        timeline.append({
            "version": e.get("to_version") or payload.get("version"),
            "from_version": e.get("from_version"),
            "op": e.get("op"), "ts": e.get("ts"), "actor": _actor(e),
            "reason": e.get("reason", ""), "event_id": e.get("event_id"),
            "changes": _diff(prev, payload) if prev is not None else _diff({}, payload),
        })
        prev = payload
    return {"entity_type": entity_type, "entity_id": entity_id, "revisions": len(timeline), "timeline": timeline}


def compare_versions(entity_type: str, entity_id: str, va, vb, log_path: str | None = None) -> dict:
    """Diff two specific versions of an entity (order-independent)."""
    snaps = {}
    for e in _events(log_path):
        if e.get("entity_type") == entity_type and e.get("entity_id") == entity_id:
            v = e.get("to_version") or (e.get("payload") or {}).get("version")
            snaps[v] = e.get("payload") or {}
    a, b = snaps.get(va), snaps.get(vb)
    lo, hi = (va, vb) if (va or 0) <= (vb or 0) else (vb, va)
    return {"entity_type": entity_type, "entity_id": entity_id, "from": lo, "to": hi,
            "changes": _diff(snaps.get(lo), snaps.get(hi))}


def model_changes(log_path: str | None = None, limit: int = 200) -> dict:
    """The recent change stream + a per-type summary of how many entities were
    created / updated / retired since the seed baseline."""
    evs = _events(log_path)
    recent = []
    for e in evs[-limit:][::-1]:
        recent.append({"entity_type": e.get("entity_type"), "entity_id": e.get("entity_id"),
                       "op": e.get("op"), "version": e.get("to_version"),
                       "ts": e.get("ts"), "actor": _actor(e), "reason": e.get("reason", "")})
    opkey = {"create": "created", "update": "updated", "deprecate": "deprecated", "restore": "updated"}
    summary: dict[str, dict] = {}
    seen_created: dict[str, set] = {}
    for e in evs:
        t = e.get("entity_type")
        s = summary.setdefault(t, {"created": 0, "updated": 0, "deprecated": 0, "entities": 0})
        key = opkey.get(e.get("op"))
        if key:
            s[key] += 1
        seen_created.setdefault(t, set()).add(e.get("entity_id"))
    for t, s in summary.items():
        s["entities"] = len(seen_created.get(t, set()))
    chain = cc.verify_log(log_path or cc.EDITS_LOG)
    return {"total_changes": len(evs), "by_type": summary, "recent": recent,
            "chain_intact": bool(chain.get("ok"))}


if __name__ == "__main__":
    print(json.dumps(model_changes(), indent=2)[:1500])
