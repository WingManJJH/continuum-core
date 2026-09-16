"""Sub-process drill-down write-path tests (D28). Plain asserts.

    python3 test_subprocess.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import mapdata  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def rejects(fn, needle=""):
    try:
        fn(); return False
    except gov.EditError as e:
        return needle in str(e)


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    T = "CO.3.2.7.t1"
    A = "role.ops.support_lead"

    # 1. set a drill-down to an existing process, versioned
    r = s.edit_task(T, {"subprocess_ref": "FN.9.3.1"}, A, "t1 expands into expenses")
    check("subprocess_ref set + version bumped", r.get("subprocess_ref") == "FN.9.3.1" and r["version"] == 2)

    # 2. it surfaces on the map payload
    m = next(x for x in mapdata.all_maps() if x["id"] == "CO.3.2.7")
    t1 = next(t for t in m["tasks"] if t["id"] == T)
    check("mapdata exposes task.subprocess", t1["subprocess"] == "FN.9.3.1")

    # 3. guards
    check("unknown sub-process refused", rejects(lambda: s.edit_task(T, {"subprocess_ref": "ZZ.9.9.9"}, A, "x"), "unknown sub-process"))
    check("drilling into own process refused", rejects(lambda: s.edit_task(T, {"subprocess_ref": "CO.3.2.7"}, A, "x"), "own process"))

    # 4. clearing it makes the step a leaf again
    r2 = s.edit_task(T, {"subprocess_ref": None}, A, "flatten")
    check("subprocess_ref cleared to null", r2.get("subprocess_ref") is None)
    m = next(x for x in mapdata.all_maps() if x["id"] == "CO.3.2.7")
    check("mapdata shows no drill-down after clear", next(t for t in m["tasks"] if t["id"] == T)["subprocess"] is None)

    # 5. still a required-reason, audited edit like any other
    check("empty reason refused", rejects(lambda: s.edit_task(T, {"subprocess_ref": "FN.9.3.1"}, A, "  "), ""))
    check("audit chain intact", cc.verify_log(cc.EDITS_LOG)["ok"])

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
