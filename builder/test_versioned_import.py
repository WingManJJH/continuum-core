"""Versioned re-import (D51): an import never overwrites a record. Plain asserts;
runs in a private models dir (files by default, Postgres in the replay group).

    python3 builder/test_versioned_import.py
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp_server"))
sys.path.insert(0, os.path.join(ROOT, "governance"))
sys.path.insert(0, HERE)

import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import versioned_import as vi  # noqa: E402
import model_import  # noqa: E402

PASS, FAIL = [], []
A = "role.ops.head_of_operations"
SRC = "Test catalog export"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False
    except exc:
        return True


def main():
    tmp = tempfile.mkdtemp()
    saved = cc.MODELS_DIR
    cc.MODELS_DIR = tmp
    try:
        run(json.load(open(os.path.join(ROOT, "data", "seed.json"))))
    finally:
        cc.MODELS_DIR = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


def proc(seed, pid):
    return next(p for p in seed["Process"] if p["id"] == pid)


def run(seed0):
    slug = "vtest"
    s = gov.GovernanceStore()

    def graph():
        with cc.use_model(slug):
            return cc.Graph()

    # 1. first import = the baseline
    model_import.write_model(slug, "Versioned test", seed0, SRC, "synthetic")
    rep = model_import.write_model.last_report
    check("first import writes the baseline", rep["kind"] == "baseline" and rep["created"] > 30)
    check("the model is registered", slug in [m["slug"] for m in cc.list_models()])

    # 2. identical re-import changes nothing
    rep = vi.import_model(slug, "Versioned test", seed0, SRC, actor=A)
    check("identical re-import writes no events", rep["events"] == 0 and rep["staged"] == 0
          and rep["unchanged"] > 30 and rep["created"] == 0)

    # 3. source changes a record nobody touched -> fast-forward
    seed1 = copy.deepcopy(seed0)
    proc(seed1, "FN.9.3.1")["name"] = "Process expense reports (v2)"
    rep = vi.import_model(slug, "Versioned test", seed1, SRC, actor=A)
    g = graph()
    check("untouched record fast-forwards", rep["updated"] == 1 and g.get("Process", "FN.9.3.1")["name"].endswith("(v2)")
          and g.get("Process", "FN.9.3.1")["version"] == proc(seed0, "FN.9.3.1")["version"] + 1)

    # 4. record edited in Continuum, then the source changes it -> staged, untouched
    with cc.use_model(slug):
        s.edit_process("CO.3.2.7", {"name": "KYC — edited in Continuum"}, A, "local improvement")
    seed2 = copy.deepcopy(seed1)
    proc(seed2, "CO.3.2.7")["name"] = "KYC — from the source"
    proc(seed2, "CO.3.2.7")["maturity_score"] = 4
    plan = vi.plan(slug, seed2, SRC)
    check("plan() writes nothing and reports the stage", plan["staged"] == 1 and not vi.staged(slug))
    rep = vi.import_model(slug, "Versioned test", seed2, SRC, actor=A)
    g = graph()
    check("edited record is NOT overwritten", g.get("Process", "CO.3.2.7")["name"] == "KYC — edited in Continuum")
    st = vi.staged(slug)
    check("the incoming version is staged with a field diff", rep["staged"] == 1 and len(st) == 1
          and {d["field"] for d in st[0]["diff"]} == {"name", "maturity_score"})
    sid = st[0]["sid"]

    # 5. stale accept is refused; a fresh accept applies
    with cc.use_model(slug):
        s.edit_process("CO.3.2.7", {"maturity_score": 3}, A, "another local edit")
    check("accept refused when the record moved after staging", raises(vi.StaleError, vi.accept, slug, sid, A))
    rep = vi.import_model(slug, "Versioned test", seed2, SRC, actor=A)
    st = vi.staged(slug)
    check("re-import supersedes the older pending change", len(st) == 1 and st[0]["sid"] != sid
          and vi.staged(slug, "superseded")[0]["sid"] == sid)
    sid = st[0]["sid"]
    r = vi.accept(slug, sid, A, expected_version=graph().get("Process", "CO.3.2.7")["version"])
    g = graph()
    check("accept applies the incoming version as a new version", g.get("Process", "CO.3.2.7")["name"] == "KYC — from the source"
          and g.get("Process", "CO.3.2.7")["version"] == r["version"])
    check("accepted twice is refused", raises(vi.ImportError_, vi.accept, slug, sid, A))

    # 6. reject is remembered while nothing changes
    with cc.use_model(slug):
        s.edit_process("SC.4.3.6", {"name": "Match POs — local"}, A, "local")
    seed3 = copy.deepcopy(seed2)
    proc(seed3, "SC.4.3.6")["name"] = "Match POs — source"
    proc(seed3, "CO.3.2.7")["name"] = "KYC — from the source"
    vi.import_model(slug, "Versioned test", seed3, SRC, actor=A)
    sid = vi.staged(slug)[0]["sid"]
    check("reject needs a reason", raises(vi.ImportError_, vi.reject, slug, sid, A, " "))
    vi.reject(slug, sid, A, "we keep our wording")
    rep = vi.import_model(slug, "Versioned test", seed3, SRC, actor=A)
    check("a rejected change is not raised again", rep["staged"] == 0 and rep["skipped_rejected"] == 1)
    proc(seed3, "SC.4.3.6")["name"] = "Match POs — source v2"
    rep = vi.import_model(slug, "Versioned test", seed3, SRC, actor=A)
    check("…but is raised again when the source changes it", rep["staged"] == 1)
    vi.reject(slug, vi.staged(slug)[0]["sid"], A, "still ours")

    # 7. removal: untouched -> retired; edited -> staged delete
    seed4 = copy.deepcopy(seed3)
    seed4["Process"] = [p for p in seed4["Process"] if p["id"] not in ("MS.3.5.2", "SC.4.3.6")]
    rep = vi.import_model(slug, "Versioned test", seed4, SRC, actor=A)
    g = graph()
    check("removed + untouched record is retired, not deleted", g.get("Process", "MS.3.5.2")["status"] == "deprecated")
    st = [x for x in vi.staged(slug) if x["id"] == "SC.4.3.6"]
    check("removed + edited record: retirement is staged", len(st) == 1 and st[0]["change"] == "delete"
          and g.get("Process", "SC.4.3.6")["status"] == "active")

    # 8. a new record is created
    seed5 = copy.deepcopy(seed4)
    newp = dict(proc(seed0, "FN.9.3.1"), id="FN.9.3.9", apqc_code="FN.9.3.9", name="Brand new process")
    seed5["Process"].append(newp)
    rep = vi.import_model(slug, "Versioned test", seed5, SRC, actor=A)
    check("new record is created", rep["created"] == 1 and graph().get("Process", "FN.9.3.9") is not None)
    batch = rep["batch"]

    # 9. revert a batch; records edited after the import are skipped
    seed6 = copy.deepcopy(seed5)
    proc(seed6, "FN.9.3.1")["name"] = "Expense v3"
    proc(seed6, "IT.8.4.2")["name"] = "Access review v3"
    rep6 = vi.import_model(slug, "Versioned test", seed6, SRC, actor=A)
    with cc.use_model(slug):
        s.edit_process("IT.8.4.2", {"name": "Access review — fixed locally"}, A, "after import")
    out = vi.revert(slug, rep6["batch"], A, "bad export")
    g = graph()
    check("revert restores what the import changed", g.get("Process", "FN.9.3.1")["name"].endswith("(v2)"))
    check("revert skips a record edited after the import, and says so",
          g.get("Process", "IT.8.4.2")["name"] == "Access review — fixed locally"
          and [x["id"] for x in out["skipped"]] == ["IT.8.4.2"])
    check("a batch can't be reverted twice", raises(vi.ImportError_, vi.revert, slug, rep6["batch"], A, "again"))
    out = vi.revert(slug, batch, A, "undo the new process")
    check("reverting a create retires the record", graph().get("Process", "FN.9.3.9")["status"] == "deprecated")

    # 10. models imported before D51 (no baseline file): the seed is the baseline
    legacy = "legacy"
    base = cc.model_base(legacy)
    os.makedirs(base, exist_ok=True)
    cc.storage.get().write_json(os.path.join(base, "seed.json"), seed0)
    cc.storage.get().write_json(os.path.join(base, "model.json"), {"name": "Legacy", "source": SRC, "description": ""})
    with cc.use_model(legacy):
        s.edit_process("CO.3.2.7", {"name": "legacy local edit"}, A, "edit")
    seedL = copy.deepcopy(seed0)
    proc(seedL, "CO.3.2.7")["name"] = "legacy source"
    proc(seedL, "FN.9.3.1")["name"] = "legacy source FN"
    rep = vi.import_model(legacy, "Legacy", seedL, SRC, actor=A)
    with cc.use_model(legacy):
        gl = cc.Graph()
    check("legacy model: untouched record fast-forwards", gl.get("Process", "FN.9.3.1")["name"] == "legacy source FN")
    check("legacy model: edited record is staged, not overwritten", gl.get("Process", "CO.3.2.7")["name"] == "legacy local edit"
          and rep["staged"] == 1)
    with cc.use_model(legacy):
        seed_now = cc.storage.get().read_json(cc.DATA)
    check("the seed baseline is never rewritten by a re-import", seed_now == seed0)

    # 11. audit
    with cc.use_model(slug):
        ok = all(cc.verify_log(os.path.join(cc.model_base(slug), n))["ok"]
                 for n in ("edits.log.jsonl", "imports.log.jsonl", "staged.log.jsonl"))
        evs = cc.read_log()
    check("edits, imports and staged logs all verify", ok)
    check("every import write names its batch and actor", all(e["actor"]["id"] for e in evs)
          and any("import B" in e["reason"] for e in evs))
    check("batches are listed with who / when / counts", [b["batch"] for b in vi.batches(slug)][:2] == ["B0001", "B0002"])
    review_fixes(seed0, s)
    one_inbox(seed0, s)


def review_fixes(seed0, s):
    """Regression tests for the 2026-10-01 independent review (D54)."""
    import threading
    # versionless seeds re-import without crashing
    bare = copy.deepcopy(seed0)
    for rows in bare.values():
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict):
                    r.pop("version", None)
    vi.import_model("bare", "Bare", bare, SRC, actor=A)
    with cc.use_model("bare"):
        s.edit_process("CO.3.2.7", {"name": "local"}, A, "edit")
    b2 = copy.deepcopy(bare)
    proc(b2, "CO.3.2.7")["name"] = "src"
    proc(b2, "FN.9.3.1")["name"] = "src FN"
    try:
        rep = vi.import_model("bare", "Bare", b2, SRC, actor=A)
        ok = rep["staged"] == 1 and rep["updated"] == 1
    except Exception as e:  # noqa: BLE001
        ok, rep = False, repr(e)
    check("seeds without version fields re-import (fast-forward + stage)", ok, str(rep)[:200])

    # a newer import that no longer proposes a change withdraws the pending one
    slug = "sup"
    vi.import_model(slug, "Sup", seed0, SRC, actor=A)
    with cc.use_model(slug):
        s.edit_process("CO.3.2.7", {"name": "ours"}, A, "edit")
    s1 = copy.deepcopy(seed0)
    proc(s1, "CO.3.2.7")["name"] = "theirs v2"
    vi.import_model(slug, "Sup", s1, SRC, actor=A)
    old_sid = vi.staged(slug)[0]["sid"]
    s2 = copy.deepcopy(seed0)
    proc(s2, "CO.3.2.7")["name"] = "ours"   # the source now agrees with us
    vi.import_model(slug, "Sup", s2, SRC, actor=A)
    check("a pending change the source no longer proposes is superseded", not vi.staged(slug)
          and old_sid in [x["sid"] for x in vi.staged(slug, "superseded")])

    # accept moves the baseline: the next source change fast-forwards
    with cc.use_model(slug):
        s.edit_process("CO.3.2.7", {"name": "ours again"}, A, "edit")
    s3 = copy.deepcopy(s2)
    proc(s3, "CO.3.2.7")["name"] = "theirs v3"
    vi.import_model(slug, "Sup", s3, SRC, actor=A)
    sid = vi.staged(slug)[0]["sid"]
    vi.accept(slug, sid, A)
    s4 = copy.deepcopy(s3)
    proc(s4, "CO.3.2.7")["name"] = "theirs v4"
    rep = vi.import_model(slug, "Sup", s4, SRC, actor=A)
    check("after an accept, the next source change fast-forwards", rep["updated"] == 1 and rep["staged"] == 0, str(rep)[:200])

    # revert marks records: re-running the same import holds them for review, with the reason
    s5 = copy.deepcopy(s4)
    proc(s5, "FN.9.3.1")["name"] = "bad export"
    r5 = vi.import_model(slug, "Sup", s5, SRC, actor=A)
    vi.revert(slug, r5["batch"], A, "bad export")
    rep = vi.import_model(slug, "Sup", s5, SRC, actor=A)
    st = [x for x in vi.staged(slug) if x["id"] == "FN.9.3.1"]
    check("re-running a reverted import holds it for review, saying why", rep["updated"] == 0 and len(st) == 1
          and "reverted" in st[0]["reasons"][0], str(st)[:200])

    # a batch that fails part-way can still be reverted
    s6 = copy.deepcopy(s4)
    s6["Process"].insert(0, dict(proc(seed0, "FN.9.3.1"), id="FN.9.3.7", apqc_code="FN.9.3.7", name="new one"))
    proc(s6, "SC.4.3.6")["name"] = "will conflict"
    real = cc.append_edit_event

    def flaky(etype, eid, *a, **k):
        if eid == "SC.4.3.6":
            raise cc.ConflictError(etype, eid, 1, 2)
        return real(etype, eid, *a, **k)
    cc.append_edit_event = flaky
    try:
        vi.import_model(slug, "Sup", s6, SRC, actor=A)
        failed = False
    except cc.ConflictError:
        failed = True
    finally:
        cc.append_edit_event = real
    fb = [b for b in vi.batches(slug) if b["kind"] == "import-failed"]
    check("a part-way failure is recorded with what it wrote", failed and fb and fb[-1]["events"][0]["id"] == "FN.9.3.7")
    out = vi.revert(slug, fb[-1]["batch"], A, "clean up the failed batch")
    with cc.use_model(slug):
        gone = cc.Graph().get("Process", "FN.9.3.7")["status"] == "deprecated"
    check("…and can be reverted", out["reverted"] == 1 and gone)

    # two imports at once get distinct batch ids (one import per model at a time)
    ids, errs = [], []

    def go(n):
        try:
            sx = copy.deepcopy(s4)
            proc(sx, "PD.2.4.1")["name"] = f"parallel {n}"
            ids.append(vi.import_model(slug, "Sup", sx, SRC, actor=A)["batch"])
        except Exception as e:  # noqa: BLE001
            errs.append(repr(e))
    ts = [threading.Thread(target=go, args=(n,)) for n in range(3)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("concurrent imports are serialized with distinct batch ids", not errs and len(set(ids)) == 3, f"{ids} {errs}")
    with cc.use_model(slug):
        check("all import logs still verify", all(cc.verify_log(os.path.join(cc.model_base(slug), n))["ok"]
              for n in ("edits.log.jsonl", "imports.log.jsonl", "staged.log.jsonl")))


def one_inbox(seed0, s):
    """D56: every staged import change is also a change request in the approvals inbox."""
    import approvals
    slug = "inbox"
    vi.import_model(slug, "Inbox", seed0, SRC, actor=A)
    with cc.use_model(slug):
        s.edit_process("CO.3.2.7", {"name": "ours"}, A, "edit")
        s.edit_process("FN.9.3.1", {"name": "ours FN"}, A, "edit")
        s.edit_process("SC.4.3.6", {"name": "ours SC"}, A, "edit")
    s1 = copy.deepcopy(seed0)
    for pid in ("CO.3.2.7", "FN.9.3.1", "SC.4.3.6"):
        proc(s1, pid)["name"] = "theirs " + pid
    vi.import_model(slug, "Inbox", s1, SRC, actor=A)
    with cc.use_model(slug):
        q = approvals.ApprovalQueue(s)
        crs = {c["target"]: c for c in q.list("pending") if c["op"] == "accept_import_change"}
        check("each staged change is a pending request in the approvals inbox", set(crs) == {"CO.3.2.7", "FN.9.3.1", "SC.4.3.6"}
              and all(c["title"].startswith("Import B") for c in crs.values()))
        q.approve(crs["CO.3.2.7"]["id"], reviewer="role.qms.iso_advisor", decision_reason="ok")
        g = cc.Graph()
        st = {x["id"]: x for x in vi.staged(slug, "all")}
        check("approving in the inbox applies the incoming version", g.get("Process", "CO.3.2.7")["name"] == "theirs CO.3.2.7"
              and st["CO.3.2.7"]["status"] == "accepted")
        q.reject(crs["FN.9.3.1"]["id"], reviewer="role.qms.iso_advisor", decision_reason="keep ours")
        st = {x["id"]: x for x in vi.staged(slug, "all")}
        check("rejecting in the inbox keeps ours and is remembered", cc.Graph().get("Process", "FN.9.3.1")["name"] == "ours FN"
              and st["FN.9.3.1"]["status"] == "rejected")
        try:
            q.withdraw(crs["SC.4.3.6"]["id"], actor=crs["SC.4.3.6"]["proposed_by"])
            refused = False
        except approvals.ApprovalError:
            refused = True
        check("an import request can't be withdrawn (approve or reject it)", refused)
    vi.accept(slug, st["SC.4.3.6"]["sid"], "role.qms.iso_advisor")
    with cc.use_model(slug):
        cr = approvals.ApprovalQueue(s).get(crs["SC.4.3.6"]["id"])
    check("deciding on the Imports screen also closes the inbox request", cr["status"] == "approved")
    with cc.use_model(slug):
        s.edit_process("PD.2.4.1", {"name": "ours PD"}, A, "edit")
    s2 = copy.deepcopy(s1)
    proc(s2, "PD.2.4.1")["name"] = "theirs PD"
    r2 = vi.import_model(slug, "Inbox", s2, SRC, actor=A)
    s3 = copy.deepcopy(s2)
    proc(s3, "PD.2.4.1")["name"] = "theirs PD v2"
    vi.import_model(slug, "Inbox", s3, SRC, actor=A)
    with cc.use_model(slug):
        pd = [c for c in approvals.ApprovalQueue(s).list(None) if c["target"] == "PD.2.4.1"]
    check("a superseded staged change closes its inbox request (one pending, one superseded)",
          sorted(c["status"] for c in pd) == ["pending", "superseded"])
    vi.revert(slug, vi.batches(slug)[-1]["batch"], A, "undo")
    with cc.use_model(slug):
        pd = [c for c in approvals.ApprovalQueue(s).list(None) if c["target"] == "PD.2.4.1"]
    check("reverting the batch withdraws its pending inbox request", all(c["status"] != "pending" for c in pd))
    with cc.use_model(slug):
        check("the proposals log verifies", cc.verify_log(os.path.join(cc.model_base(slug), "proposals.log.jsonl"))["ok"])


if __name__ == "__main__":
    main()
