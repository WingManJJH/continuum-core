"""Storage contract on the active backend (D48/D50): optimistic concurrency under
thread and process contention, atomic chained appends, per-request isolation.
Runs on files by default and on Postgres in the replay group.

    python3 mcp_server/test_storage.py
"""
from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import storage  # noqa: E402

PASS, FAIL = [], []
ACTOR = {"kind": "human", "id": "role.ops.support_lead"}


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def _proc_worker(args):
    tmp, i, cur = args
    cc.DATA, cc.EDITS_LOG, cc.HEADS_FILE = (os.path.join(tmp, n) for n in ("seed.json", "edits.log.jsonl", "audit_heads.json"))
    body = dict(cur, version=cur["version"] + 1, escalate_if=f"p{i}")
    try:
        cc.append_edit_event("GuardrailPolicy", cur["id"], "update", cur["version"], cur["version"] + 1, ACTOR, body, f"p{i}")
        return "ok"
    except cc.ConflictError:
        return "conflict"


def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(HERE, "..", "data", "seed.json"), os.path.join(tmp, "seed.json"))
    saved = (cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE)
    cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE = (
        os.path.join(tmp, n) for n in ("seed.json", "edits.log.jsonl", "events.log.jsonl", "audit_heads.json"))
    try:
        be = storage.get()
        print(f"  backend: {be.kind}")
        g = cc.Graph()
        cur = g.get("GuardrailPolicy", "gr.CO.3.2.7")
        ok = dict(cur, version=cur["version"] + 1)
        cc.append_edit_event("GuardrailPolicy", cur["id"], "update", cur["version"], ok["version"], ACTOR, ok, "fresh")
        check("a write from the current version succeeds", cc.Graph().get("GuardrailPolicy", cur["id"])["version"] == ok["version"])
        try:
            cc.append_edit_event("GuardrailPolicy", cur["id"], "update", cur["version"], ok["version"], ACTOR, ok, "stale")
            stale = False
        except cc.ConflictError as e:
            stale = "changed since you opened it" in str(e) and e.current == ok["version"]
        check("a write from a stale version is refused with the current version", stale)
        try:
            cc.append_edit_event("GuardrailPolicy", cur["id"], "create", None, 1, ACTOR, dict(cur, version=1), "dup")
            dup = False
        except cc.ConflictError:
            dup = True
        check("creating an id that already exists is refused", dup)
        before = len(cc.read_log())
        check("refused writes append nothing", before == 1)

        # thread contention
        cur = cc.Graph().get("GuardrailPolicy", cur["id"])
        res, bar = [], threading.Barrier(10)

        def w(i):
            body = dict(cur, version=cur["version"] + 1, escalate_if=f"t{i}")
            bar.wait()
            try:
                cc.append_edit_event("GuardrailPolicy", cur["id"], "update", cur["version"], body["version"], ACTOR, body, f"t{i}")
                res.append("ok")
            except cc.ConflictError:
                res.append("conflict")
        ts = [threading.Thread(target=w, args=(i,)) for i in range(10)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check("10 threads, one read: exactly one write wins", res.count("ok") == 1 and res.count("conflict") == 9, str(res))

        # process contention (run.py runs five apps as separate processes)
        cur = cc.Graph().get("GuardrailPolicy", cur["id"])
        with mp.get_context("spawn").Pool(6) as pool:
            pres = pool.map(_proc_worker, [(tmp, i, cur) for i in range(6)])
        check("6 processes, one read: exactly one write wins", pres.count("ok") == 1, str(pres))
        v = cc.verify_log(cc.EDITS_LOG)
        check("chain and heads anchor intact after contention", v["ok"] and v["count"] == len(cc.read_log()), str(v))
        vers = [e["to_version"] for e in cc.read_log()]
        check("versions strictly increase (no lost or duplicate write)", vers == sorted(set(vers)), str(vers))

        # documents are written atomically and read back exactly
        doc = {"a": [1, 2.5, None], "ü": "✓"}
        be.write_json(os.path.join(tmp, "layout.json"), doc)
        check("documents round-trip", be.read_json(os.path.join(tmp, "layout.json")) == doc)
        check("a missing document returns the default", be.read_json(os.path.join(tmp, "nope.json"), {"d": 1}) == {"d": 1})
        be.append_line(os.path.join(tmp, "escalations.jsonl"), {"x": 1})
        be.append_line(os.path.join(tmp, "escalations.jsonl"), {"x": 2})
        check("plain logs append in order", [r["x"] for r in be.read_lines(os.path.join(tmp, "escalations.jsonl"))] == [1, 2])
        be.remove(os.path.join(tmp, "escalations.jsonl"))
        check("plain logs can be cleared", be.read_lines(os.path.join(tmp, "escalations.jsonl")) == [])
    finally:
        cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
