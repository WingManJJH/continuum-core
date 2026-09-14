"""Task write-path tests (D14) — add / rename / reorder / remove a step, versioned
and chain-safe. Uses the real edit log; cleans it up.

    python3 test_taskedit.py
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


def active(pid):
    g = cc.Graph()
    return sorted((t for t in g.all("Task") if t["process_ref"] == pid and t["status"] == "active"),
                  key=lambda t: t["seq"])


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()

    check("CO.3.2.7 starts with 4 active steps", len(active("CO.3.2.7")) == 4)

    # 1. ADD a step -> appears in the folded graph as a new active task
    new = s.add_task("CO.3.2.7", "Notify customer", A, "add a notification step")
    check("add_task returns a new id at the end", new["id"] == "CO.3.2.7.t5" and new["seq"] == 5)
    a = active("CO.3.2.7")
    check("MCP-side graph sees 5 active steps", len(a) == 5)
    check("new step inherits the process guardrail (guardrail_ref null)", new["guardrail_ref"] is None
          and cc.Graph().effective_guardrail("CO.3.2.7.t5")[1] == "gr.CO.3.2.7.v3")

    # 2. RENAME (edit) -> version bump, name changed live
    ed = s.edit_task("CO.3.2.7.t5", {"name": "Notify the customer"}, A, "clarify wording")
    check("edit_task bumps version 1 -> 2", ed["version"] == 2)
    check("rename is live in the graph", cc.Graph().get("Task", "CO.3.2.7.t5")["name"] == "Notify the customer")

    # 3. MOVE up -> swaps seq with the previous step (both versioned)
    s.move_task("CO.3.2.7.t5", "up", A)
    a = active("CO.3.2.7")
    order = [t["id"] for t in a]
    check("move up reorders t5 before t4", order.index("CO.3.2.7.t5") < order.index("CO.3.2.7.t4"))

    # 4. REMOVE -> deprecated, drops out of the active/canvas set (never hard-deleted)
    rm = s.remove_task("CO.3.2.7.t5", A, "not needed after all")
    check("remove_task deprecates the step", rm["status"] == "deprecated")
    check("removed step is gone from the active set", len(active("CO.3.2.7")) == 4)
    check("but the record is retained (not destroyed)", cc.Graph().get("Task", "CO.3.2.7.t5") is not None)

    # 5. validation / §7.5
    def rejects(fn):
        try:
            fn(); return False
        except gov.EditError:
            return True
    check("unknown performer role rejected", rejects(lambda: s.edit_task("CO.3.2.7.t3", {"performed_by": ["role.does.not.exist"]}, A, "x")))
    check("non-editable field rejected", rejects(lambda: s.edit_task("CO.3.2.7.t3", {"id": "CO.3.2.7.t9"}, A, "x")))
    check("empty step name rejected on add", rejects(lambda: s.add_task("CO.3.2.7", "   ", A, "x")))
    check("missing reason rejected (§7.5)", rejects(lambda: s.edit_task("CO.3.2.7.t3", {"name": "X"}, A, "  ")))
    check("move past the end rejected", rejects(lambda: s.move_task("CO.3.2.7.t4", "down", A)))

    # 6. the whole structural-edit sequence stayed on an intact hash chain
    check("audit chain intact after structural edits", cc.verify_log(cc.EDITS_LOG)["ok"])

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
