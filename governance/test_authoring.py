"""Authoring write-path tests (D15) — create a process (auto default guardrail) and
insert steps positionally. Uses the real edit log; cleans it up.

    python3 test_authoring.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402

PASS, FAIL = [], []
A = "role.ops.support_lead"


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def seqs(pid):
    g = cc.Graph()
    return [(t["seq"], t["id"]) for t in sorted(
        (t for t in g.all("Task") if t["process_ref"] == pid and t["status"] == "active"),
        key=lambda t: t["seq"])]


def rejects(fn):
    try:
        fn(); return False
    except gov.EditError:
        return True


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()

    # 1. author a brand-new process — stamped with the default guardrail
    p = s.add_process("QA.5.1.1", "Handle a customer complaint", "role.ops.support_lead", A, "author QA process")
    check("add_process creates the process", cc.Graph().get("Process", "QA.5.1.1") is not None)
    check("new process references its own default guardrail", p["guardrail_ref"] == "gr.QA.5.1.1")
    g = cc.Graph()
    gr = g.get("GuardrailPolicy", "gr.QA.5.1.1")
    check("default guardrail was created v1", gr and gr["version"] == 1)
    check("default guardrail is UNREVIEWED (counts as default for §12)", "review" not in gr)
    check("new process starts with 0 steps", seqs("QA.5.1.1") == [])

    # 2. add steps; a step inherits the process guardrail
    t1 = s.add_task("QA.5.1.1", "Log the complaint", A, "step 1")
    s.add_task("QA.5.1.1", "Resolve or escalate", A, "step 3 (append)")
    check("appended two steps", [x[0] for x in seqs("QA.5.1.1")] == [1, 2])
    check("new step inherits the process default guardrail",
          cc.Graph().effective_guardrail(t1["id"])[1] == "gr.QA.5.1.1.v1")

    # 3. positional insert — after t1 -> becomes seq 2, pushes the old seq-2 down
    ins = s.add_task("QA.5.1.1", "Acknowledge to customer", A, "insert after step 1", after=t1["id"])
    order = seqs("QA.5.1.1")
    check("insert-after places the new step at seq 2", ins["seq"] == 2)
    check("the tail shifted down (3 steps now, contiguous)", [x[0] for x in order] == [1, 2, 3])
    check("inserted step sits directly after t1", order[1][1] == ins["id"])

    # 4. prepend
    pre = s.add_task("QA.5.1.1", "Intake", A, "prepend", after="__start__")
    check("prepend places a step at seq 1", pre["seq"] == 1 and seqs("QA.5.1.1")[0][1] == pre["id"])
    check("all steps contiguous after prepend", [x[0] for x in seqs("QA.5.1.1")] == [1, 2, 3, 4])

    # 5. validation
    check("duplicate process code rejected", rejects(lambda: s.add_process("QA.5.1.1", "x", A, A, "r")))
    check("bad code rejected", rejects(lambda: s.add_process("not a code", "x", A, A, "r")))
    check("unknown owner role rejected", rejects(lambda: s.add_process("QB.1.1.1", "x", "role.ghost", A, "r")))
    check("insert after unknown step rejected", rejects(lambda: s.add_task("QA.5.1.1", "x", A, "r", after="QA.5.1.1.t99")))

    # 6. the whole authoring sequence stayed on an intact chain, and the new process
    #    is not a data-quality defect it wasn't meant to be (it has a guardrail + owner)
    check("audit chain intact after authoring", cc.verify_log(cc.EDITS_LOG)["ok"])
    np = cc.Graph().get("Process", "QA.5.1.1")
    check("authored process has owner + guardrail (no dangling)", np["owner_role"] and np["guardrail_ref"])

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
