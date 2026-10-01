"""Versioned re-import — an import never overwrites a record (D51).

Re-importing a model (BPC / OC / Sunrise / SYSPRO / any seed-shaped source) used to
rewrite the model's `seed.json`, so a record edited in Continuum could silently
lose the edit (or the import's change could silently vanish under it), and the
ISO 9001 §7.5 baseline itself was rewritten.

Now the first import of a model writes its seed baseline; every later import is a
numbered **batch** of ordinary change-control events, and each import source keeps
a **baseline** — the version of each record it last wrote:

  record                                   what the import does
  --------------------------------------   -----------------------------------------
  new                                      creates it
  same as stored                           nothing (baseline moves forward)
  unchanged since this source wrote it     updates it (fast-forward)
  changed in Continuum since               leaves it untouched; STAGES the incoming
                                           version for review, field by field
  gone from the source, untouched since    retires it (status deprecated, never deleted)
  gone from the source, edited since       stages the retirement for review

Reviewers accept or reject staged changes. Accept is refused if the record moved
after staging (the reviewer must look again). A rejected change is not raised again
while the record and the incoming version are unchanged; a newer import supersedes
older pending changes for the same record. A whole batch can be reverted with
compensating events (history is never rewritten); a revert skips any record edited
after the import and says so.

All state lives in the model's own logs (works on files and Postgres):
  imports.log.jsonl  — chained: one record per batch / revert
  staged.log.jsonl   — chained: stage / decide events, folded into the review queue
  import_baselines.json — per source: "Type|id" -> version last written
Models imported before this existed use their seed as the baseline.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

IGNORED = {"version"}  # compared content excludes the version counter


class ImportError_(ValueError):
    """A refused import / review decision — safe to show in the UI."""


class StaleError(ImportError_):
    """The record moved after the change was staged (HTTP 409)."""


def _now():
    return datetime.now(timezone.utc).isoformat()


def _key(etype, eid):
    return f"{etype}|{eid}"


def _content(rec: dict) -> dict:
    return {k: v for k, v in (rec or {}).items() if k not in IGNORED}


def _h(rec: dict) -> str:
    return hashlib.sha256(json.dumps(_content(rec), sort_keys=True).encode()).hexdigest()[:16]


def _diff(cur: dict, inc: dict) -> list[dict]:
    keys = sorted(set(_content(cur)) | set(_content(inc)))
    return [{"field": k, "current": cur.get(k), "incoming": inc.get(k)} for k in keys if cur.get(k) != inc.get(k)]


def _paths(slug):
    base = cc.model_base(slug)
    return {k: os.path.join(base, n) for k, n in (("seed", "seed.json"), ("meta", "model.json"),
                                                  ("imports", "imports.log.jsonl"), ("staged", "staged.log.jsonl"),
                                                  ("baselines", "import_baselines.json"))}


def _seed_items(seed: dict):
    for etype, rows in seed.items():
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and r.get("id"):
                    yield etype, r


def _actor(actor):
    return {"kind": "human", "id": actor}


def _append(path, event):
    event.setdefault("event_id", "imp_" + cc._ulidish())
    event.setdefault("ts", _now())
    return cc._append_event(path, event)


# --------------------------------------------------------------------------- review queue
def _fold_staged(slug) -> dict:
    out: dict[str, dict] = {}
    for ev in cc.read_log(_paths(slug)["staged"]):
        if ev["kind"] == "stage":
            out[ev["sid"]] = {**{k: ev[k] for k in ("sid", "batch", "etype", "id", "change", "based_on_version",
                                                    "incoming", "diff", "reasons", "incoming_hash")},
                              "staged_at": ev["ts"], "status": "pending", "decision": None}
        elif ev["sid"] in out:
            out[ev["sid"]]["status"] = ev["status"]
            out[ev["sid"]]["decision"] = {"by": ev.get("by"), "reason": ev.get("reason", ""), "at": ev["ts"],
                                          "applied_version": ev.get("applied_version")}
    return out


def staged(slug, status: str | None = "pending") -> list[dict]:
    with cc.use_model(slug, cc.current_user()):
        rows = list(_fold_staged(slug).values())
    return [r for r in rows if status in (None, "all") or r["status"] == status]


def batches(slug) -> list[dict]:
    with cc.use_model(slug, cc.current_user()):
        return [e for e in cc.read_log(_paths(slug)["imports"])]


# --------------------------------------------------------------------------- import
def plan(slug: str, seed: dict, source: str) -> dict:
    """What an import WOULD do — nothing is written."""
    return _run(slug, seed, source, actor=None, dry=True)


def import_model(slug: str, name: str, seed: dict, source: str, description: str = "",
                 actor: str = "role.import.service", reason: str = "") -> dict:
    """Import `seed` as model `slug`. A new model gets its baseline seed; an
    existing one gets a versioned batch. Returns the batch report."""
    p = _paths(slug)
    be = cc.storage.get()
    with cc.use_model(slug, cc.current_user()):
        if be.read_json(p["seed"], None) is None:
            be.write_json(p["seed"], seed, indent=1)
            be.write_json(p["meta"], {"name": name, "source": source, "description": description}, indent=1)
            base = {_key(t, r["id"]): r.get("version", 1) for t, r in _seed_items(seed)}
            bl = be.read_json(p["baselines"], {}) or {}
            bl[source] = base
            be.write_json(p["baselines"], bl)
            rep = {"batch": "B0001", "kind": "baseline", "source": source, "created": len(base), "updated": 0,
                   "retired": 0, "unchanged": 0, "staged": 0, "events": []}
            _append(p["imports"], {**rep, "actor": _actor(actor), "reason": reason or f"baseline import from {source}"})
            return rep
        meta = be.read_json(p["meta"], {}) or {}
        be.write_json(p["meta"], {**meta, "name": name or meta.get("name"), "source": source,
                                  "description": description or meta.get("description", "")}, indent=1)
    return _run(slug, seed, source, actor, dry=False, reason=reason)


def _run(slug, seed, source, actor, dry, reason=""):
    p = _paths(slug)
    be = cc.storage.get()
    with cc.use_model(slug, cc.current_user()):
        g = cc.Graph()
        base_seed = be.read_json(p["seed"], {}) or {}
        bl_all = be.read_json(p["baselines"], {}) or {}
        baseline = bl_all.get(source)
        if baseline is None:  # imported before D51: the seed is the baseline
            baseline = {_key(t, r["id"]): r.get("version", 1) for t, r in _seed_items(base_seed)}
        queue = _fold_staged(slug)
        pending_by_key = {_key(s["etype"], s["id"]): s for s in queue.values() if s["status"] == "pending"}
        rejected = {(_key(s["etype"], s["id"]), s["based_on_version"], s["incoming_hash"])
                    for s in queue.values() if s["status"] == "rejected"}
        n = len(cc.read_log(p["imports"])) + 1
        batch = f"B{n:04d}"
        rep = {"batch": batch, "kind": "import", "source": source, "created": 0, "updated": 0, "retired": 0,
               "unchanged": 0, "staged": 0, "skipped_rejected": 0, "events": [], "staged_ids": [],
               "superseded": [], "changes": []}
        new_baseline = dict(baseline)
        why = f"import {batch} from {source}" + (f" — {reason}" if reason else "")
        incoming_keys = set()

        def stage(etype, eid, change, cur, inc, reasons):
            k = _key(etype, eid)
            ih = _h(inc) if inc else "delete"
            if (k, cur["version"], ih) in rejected:
                rep["skipped_rejected"] += 1
                return
            rep["staged"] += 1
            rep["changes"].append({"etype": etype, "id": eid, "action": "stage-" + change, "reasons": reasons})
            if dry:
                return
            old = pending_by_key.get(k)
            if old:
                _append(p["staged"], {"kind": "decide", "sid": old["sid"], "status": "superseded",
                                      "by": actor, "reason": f"superseded by {batch}"})
                rep["superseded"].append(old["sid"])
            sid = f"S{batch[1:]}-{len(rep['staged_ids']) + 1:04d}"
            _append(p["staged"], {"kind": "stage", "sid": sid, "batch": batch, "etype": etype, "id": eid,
                                  "change": change, "based_on_version": cur["version"], "incoming": inc,
                                  "incoming_hash": ih, "diff": _diff(cur, inc or {}) if inc else [],
                                  "reasons": reasons})
            rep["staged_ids"].append(sid)

        def write(etype, eid, op, cur, body):
            rep["changes"].append({"etype": etype, "id": eid, "action": op})
            if dry:
                return
            ev = cc.append_edit_event(etype, eid, op, cur["version"] if cur else None, body["version"],
                                      _actor(actor), body, why)
            rep["events"].append({"event_id": ev["event_id"], "etype": etype, "id": eid, "op": op,
                                  "from_version": cur["version"] if cur else None, "to_version": body["version"],
                                  "prev": cur})
            new_baseline[_key(etype, eid)] = body["version"]

        for etype, inc in _seed_items(seed):
            if etype not in g._by_type:
                continue
            eid = inc["id"]
            k = _key(etype, eid)
            incoming_keys.add(k)
            cur = g.get(etype, eid)
            if cur is None:
                rep["created"] += 1
                write(etype, eid, "create", None, {**inc, "version": 1})
            elif _content(cur) == _content(inc):
                rep["unchanged"] += 1
                new_baseline[k] = cur["version"]
            elif k in baseline and cur.get("version") == baseline[k]:
                rep["updated"] += 1
                write(etype, eid, "update", cur, {**copy.deepcopy(inc), "version": cur["version"] + 1})
            else:
                why_staged = (["edited in Continuum since this source last imported it"] if k in baseline
                              else ["exists in Continuum but was not created by this source"])
                stage(etype, eid, "update", cur, {**copy.deepcopy(inc), "version": cur["version"] + 1}, why_staged)

        for k, ver in baseline.items():
            if k in incoming_keys:
                continue
            etype, eid = k.split("|", 1)
            cur = g.get(etype, eid) if etype in g._by_type else None
            if cur is None or cur.get("status") == "deprecated":
                new_baseline.pop(k, None)
                continue
            if cur.get("version") == ver:
                rep["retired"] += 1
                write(etype, eid, "deprecate", cur, {**copy.deepcopy(cur), "status": "deprecated",
                                                     "version": cur["version"] + 1})
                new_baseline.pop(k, None)
            else:
                stage(etype, eid, "delete", cur, None, ["removed from the source, but edited in Continuum since"])

        if dry:
            rep.pop("events")
            return rep
        bl_all[source] = new_baseline
        be.write_json(p["baselines"], bl_all)
        _append(p["imports"], {"batch": batch, "kind": "import", "source": source, "actor": _actor(actor),
                               "reason": why, **{k: rep[k] for k in ("created", "updated", "retired", "unchanged",
                                                                     "staged", "skipped_rejected", "staged_ids",
                                                                     "superseded")},
                               "events": [{k: e[k] for k in ("event_id", "etype", "id", "op", "from_version",
                                                             "to_version")} for e in rep["events"]],
                               "prev": {e["event_id"]: e["prev"] for e in rep["events"]}})
        return {k: v for k, v in rep.items() if k != "events"} | {"events": len(rep["events"])}


# --------------------------------------------------------------------------- decisions
def accept(slug, sid, actor, expected_version: int | None = None, reason: str = "") -> dict:
    with cc.use_model(slug, cc.current_user()):
        p = _paths(slug)
        s = _fold_staged(slug).get(sid)
        if not s:
            raise ImportError_(f"unknown staged change {sid}")
        if s["status"] != "pending":
            raise ImportError_(f"staged change {sid} is already {s['status']}")
        cur = cc.Graph().get(s["etype"], s["id"])
        now_v = cur.get("version") if cur else None
        if now_v != s["based_on_version"] or (expected_version is not None and expected_version != now_v):
            raise StaleError(f"{s['etype']} {s['id']} changed after this was staged (staged against "
                             f"v{s['based_on_version']}, now v{now_v}) — review it again")
        if s["change"] == "update":
            body = {**s["incoming"], "version": now_v + 1}
            op = "update"
        else:
            body = {**copy.deepcopy(cur), "status": "deprecated", "version": now_v + 1}
            op = "deprecate"
        cc.append_edit_event(s["etype"], s["id"], op, now_v, body["version"], _actor(actor), body,
                             f"accepted staged import change {sid}" + (f" — {reason}" if reason else ""))
        _append(p["staged"], {"kind": "decide", "sid": sid, "status": "accepted", "by": actor, "reason": reason,
                              "applied_version": body["version"]})
        return {"sid": sid, "status": "accepted", "version": body["version"]}


def reject(slug, sid, actor, reason: str) -> dict:
    if not (reason or "").strip():
        raise ImportError_("a reason is required to reject a staged change (ISO 9001 §7.5)")
    with cc.use_model(slug, cc.current_user()):
        p = _paths(slug)
        s = _fold_staged(slug).get(sid)
        if not s:
            raise ImportError_(f"unknown staged change {sid}")
        if s["status"] != "pending":
            raise ImportError_(f"staged change {sid} is already {s['status']}")
        _append(p["staged"], {"kind": "decide", "sid": sid, "status": "rejected", "by": actor, "reason": reason})
        return {"sid": sid, "status": "rejected"}


def revert(slug, batch: str, actor: str, reason: str) -> dict:
    """Undo a batch with compensating events. Records edited after the import are
    skipped and reported, never overwritten."""
    if not (reason or "").strip():
        raise ImportError_("a reason is required to revert an import")
    with cc.use_model(slug, cc.current_user()):
        p = _paths(slug)
        logs = cc.read_log(p["imports"])
        rec = next((e for e in logs if e.get("batch") == batch and e.get("kind") == "import"), None)
        if not rec:
            raise ImportError_(f"unknown import batch {batch}")
        if any(e.get("kind") == "revert" and e.get("batch") == batch for e in logs):
            raise ImportError_(f"import {batch} was already reverted")
        g = cc.Graph()
        done, skipped = [], []
        for ev in reversed(rec["events"]):
            cur = g.get(ev["etype"], ev["id"])
            if not cur or cur.get("version") != ev["to_version"]:
                skipped.append({"etype": ev["etype"], "id": ev["id"], "why": "edited after the import"})
                continue
            prev = rec["prev"].get(ev["event_id"])
            if prev is None:  # the import created it: retire
                body, op = {**copy.deepcopy(cur), "status": "deprecated", "version": cur["version"] + 1}, "deprecate"
            else:
                body, op = {**copy.deepcopy(prev), "version": cur["version"] + 1}, ("restore" if cur.get("status") == "deprecated" else "update")
            cc.append_edit_event(ev["etype"], ev["id"], op, cur["version"], body["version"], _actor(actor), body,
                                 f"revert import {batch} — {reason}")
            done.append({"etype": ev["etype"], "id": ev["id"], "op": op})
        # pending changes staged by that batch are withdrawn with it
        for s in _fold_staged(slug).values():
            if s["batch"] == batch and s["status"] == "pending":
                _append(p["staged"], {"kind": "decide", "sid": s["sid"], "status": "superseded", "by": actor,
                                      "reason": f"import {batch} reverted"})
        _append(p["imports"], {"batch": batch, "kind": "revert", "actor": _actor(actor), "reason": reason,
                               "reverted": len(done), "skipped": skipped})
        return {"batch": batch, "reverted": len(done), "skipped": skipped}
