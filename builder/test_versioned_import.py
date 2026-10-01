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


if __name__ == "__main__":
    main()
