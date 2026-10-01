"""Canvas API for the EA / GRC modules and import review (D45, D51, D52).

GET   /api/ea?type=Capability|Application|Obligation|Control|Risk   records (+ packs)
POST  /api/ea        {op: add|edit|retire|link|unlink|test|seed_pack|split_rc, type, id, …}
GET   /api/ripple?id=…      Ripple impact / upstream dependencies
GET   /api/assure           clause-by-clause evidence matrix (ISO 9001 / 9004 packs)
GET   /api/vitals           model health score + findings
GET   /api/atlas            capability map
GET   /api/imports          import batches (who / when / counts)
POST  /api/imports          {slug?, name, source, seed, dry} import a seed-shaped model (admin)
POST  /api/imports/revert   {batch, reason} (admin)
GET   /api/staged?status=   staged changes with field diffs
POST  /api/staged           {op: accept|reject, sid, expected_version, reason} (approver)

Every write goes through GovernanceStore / versioned_import (validated, versioned,
hash-chained, approval-policy gated). Identity comes from the guard, never the body.
"""
from __future__ import annotations

import os
import sys
from datetime import date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(HERE, "..", "builder"))
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import versioned_import as vi  # noqa: E402
from enterprise import rules  # noqa: E402

EA_TYPES = ("Capability", "Application", "Obligation", "Control", "Risk")
LABEL = {"Capability": "capability", "Application": "application", "Obligation": "obligation",
         "Control": "control", "Risk": "risk"}
GET_PATHS = {"/api/ea", "/api/ripple", "/api/assure", "/api/vitals", "/api/atlas", "/api/imports", "/api/staged"}
POST_PATHS = {"/api/ea", "/api/imports", "/api/imports/revert", "/api/staged"}


def handles(method: str, path: str) -> bool:
    return path in (GET_PATHS if method == "GET" else POST_PATHS)


def _today(q):
    return (q.get("today") or [date.today().isoformat()])[0]


def get(store: gov.GovernanceStore, path: str, q: dict):
    v = rules.View(cc.Graph())
    if path == "/api/ea":
        t = (q.get("type") or [""])[0]
        if t and t not in EA_TYPES:
            raise gov.EditError(f"unknown building block {t}")
        types = [t] if t else list(EA_TYPES)
        g = v.g
        out = {tt: sorted([e for e in g.all(tt) if e.get("status") != "deprecated"], key=lambda e: e.get("name") or
                          e.get("title") or e["id"]) for tt in types}
        return {"ok": True, "records": out,
                "packs": [{"id": k, "label": p["label"], "count": len(p["obligations"])}
                          for k, p in store.obligation_packs().items()],
                "processes": [{"id": p["id"], "name": p["name"]} for p in sorted(v.procs.values(), key=lambda x: x["id"])],
                "tasks": [{"id": t2["id"], "name": t2.get("name"), "process": t2["process_ref"]}
                          for t2 in sorted(v.tasks.values(), key=lambda x: x["id"])],
                "bindings": sorted(v.bindings), "legacy_risk_controls":
                    [{"id": r["id"], "risk": r["risk"], "process": r["process_ref"]}
                     for r in g.all("RiskControl") if r.get("status") != "deprecated"]}
    if path == "/api/ripple":
        return {"ok": True, "ripple": rules.ripple(v, (q.get("id") or [""])[0])}
    if path == "/api/assure":
        return {"ok": True, **rules.assure(v, _today(q))}
    if path == "/api/vitals":
        return {"ok": True, **rules.vitals(v, _today(q))}
    if path == "/api/atlas":
        return {"ok": True, "atlas": rules.atlas_public(rules.atlas(v)),
                "unmapped": [{"id": p["id"], "name": p["name"]} for p in v.procs.values()
                             if not any(e["s"] == p["id"] and e["type"] == "realizes" for e in v.edges)]}
    if path == "/api/imports":
        slug = cc.ACTIVE_MODEL
        return {"ok": True, "model": slug, "batches": [_batch_summary(b) for b in vi.batches(slug)][::-1],
                "pending": len(vi.staged(slug))}
    if path == "/api/staged":
        st = (q.get("status") or ["pending"])[0]
        return {"ok": True, "staged": vi.staged(cc.ACTIVE_MODEL, st)[::-1]}
    raise gov.EditError("unknown path")


def _batch_summary(b):
    return {k: b.get(k) for k in ("batch", "kind", "source", "ts", "reason", "created", "updated", "retired",
                                  "unchanged", "staged", "reverted", "skipped")} | {"actor": (b.get("actor") or {}).get("id"),
                                                                                    "user": (b.get("actor") or {}).get("user")}


def post(store: gov.GovernanceStore, path: str, b: dict, gate):
    actor, reason = b.get("actor", ""), (b.get("reason") or "").strip()
    if path == "/api/ea":
        op, t = b.get("op"), b.get("type")
        if op in ("seed_pack",):
            gate("Obligation")
            return {"ok": True, "result": store.seed_obligation_pack(b.get("pack", ""), actor, reason)}
        if op == "split_rc":
            gate("Risk"), gate("Control")
            return {"ok": True, "result": store.split_risk_control(b.get("id", ""), actor, reason or "split risk & control")}
        if t not in EA_TYPES:
            raise gov.EditError(f"unknown building block {t}")
        gate(t)
        lab = LABEL[t]
        if op == "add":
            r = getattr(store, f"add_{lab}")(b.get("fields") or {}, actor, reason or f"added {lab}")
        elif op == "edit":
            r = getattr(store, f"edit_{lab}")(b.get("id", ""), b.get("changes") or {}, actor, reason or f"edited {lab}")
        elif op == "retire":
            r = getattr(store, f"retire_{lab}")(b.get("id", ""), actor, reason or f"retired {lab}")
        elif op in ("link", "unlink"):
            fn = store.link_ea if op == "link" else store.unlink_ea
            r = fn(t, b.get("id", ""), b.get("field", ""), b.get("ref", ""), actor, reason or f"{op}ed {lab}")
        elif op == "test" and t == "Control":
            r = store.record_control_test(b.get("id", ""), b.get("result", ""), b.get("tested_on") or date.today().isoformat(),
                                          actor, reason or "recorded control test")
        else:
            raise gov.EditError(f"unknown op {op}")
        return {"ok": True, "result": r}
    if path == "/api/staged":
        op, sid = b.get("op"), b.get("sid", "")
        if op == "accept":
            return {"ok": True, "result": vi.accept(cc.ACTIVE_MODEL, sid, actor, b.get("expected_version"), reason)}
        if op == "reject":
            return {"ok": True, "result": vi.reject(cc.ACTIVE_MODEL, sid, actor, reason)}
        raise gov.EditError("op must be accept or reject")
    if path == "/api/imports/revert":
        return {"ok": True, "result": vi.revert(cc.ACTIVE_MODEL, b.get("batch", ""), actor, reason)}
    if path == "/api/imports":
        seed = b.get("seed")
        if not isinstance(seed, dict) or not isinstance(seed.get("Process"), list):
            raise gov.EditError("seed must be a model export (an object with a Process list)")
        source = (b.get("source") or "").strip()
        if not source:
            raise gov.EditError("name the source of this import (e.g. 'SYSPRO export')")
        slug = cc.ACTIVE_MODEL
        if b.get("dry"):
            return {"ok": True, "plan": vi.plan(slug, seed, source)}
        rep = vi.import_model(slug, b.get("name") or slug, seed, source, b.get("description", ""), actor=actor,
                              reason=reason)
        return {"ok": True, "result": rep}
    raise gov.EditError("unknown path")
