"""Agent-binding write-path tests (D16) — make a step agent-run / human-only from
the canvas. Uses the real edit log; cleans it up.

    python3 test_binding.py
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
A = "role.ops.support_lead"


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def perf(task_id):
    return cc.Graph().get("Task", task_id)["performed_by"]


def rejects(fn):
    try:
        fn(); return False
    except gov.EditError:
        return True


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()

    check("t1 starts human-only", not any(w.startswith("agent.") for w in perf("CO.3.2.7.t1")))

    # 1. bind an agent -> creates a binding and adds it to the step's performers
    aid = s.bind_agent("CO.3.2.7.t1", A, "automate intake")["binding"]
    check("bind_agent returns a binding id", aid == "agent.co.3.2.7.t1")
    g = cc.Graph()
    b = g.get("AgentBinding", aid)
    check("AgentBinding created, pointing at the step", b and b["task_ref"] == "CO.3.2.7.t1" and b["status"] == "active")
    check("step is now agent-bound", aid in perf("CO.3.2.7.t1"))
    check("agent step inherits the process guardrail", g.effective_guardrail("CO.3.2.7.t1")[1] == "gr.CO.3.2.7.v3")

    # 2. the canvas now renders it as an agent step
    co = next(m for m in mapdata.all_maps() if m["id"] == "CO.3.2.7")
    t1 = next(t for t in co["tasks"] if t["id"] == "CO.3.2.7.t1")
    check("mapdata shows t1 as an agent step", t1["agents"] == [aid])

    # 3. can't double-bind
    check("re-binding the same step is rejected", rejects(lambda: s.bind_agent("CO.3.2.7.t1", A, "x")))

    # 4. unbind -> human-only again; the binding is deprecated (retained, not destroyed)
    s.unbind_agent("CO.3.2.7.t1", A, "revert to human")
    check("step is human-only after unbind", not any(w.startswith("agent.") for w in perf("CO.3.2.7.t1")))
    nb = cc.Graph().get("AgentBinding", aid)
    check("binding retained but deprecated", nb is not None and nb["status"] == "deprecated")

    # 5. validation
    check("bind on unknown step rejected", rejects(lambda: s.bind_agent("CO.3.2.7.t99", A, "x")))
    check("unbind a step with no agent rejected", rejects(lambda: s.unbind_agent("CO.3.2.7.t2", A, "x")))
    check("missing reason rejected (§7.5)", rejects(lambda: s.bind_agent("CO.3.2.7.t4", A, "  ")))

    # 6. the whole bind/unbind sequence stayed on an intact chain
    check("audit chain intact after binding edits", cc.verify_log(cc.EDITS_LOG)["ok"])

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
