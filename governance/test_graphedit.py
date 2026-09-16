"""Edit-in-place tests for gateways / events / flows (D34). Plain asserts.

Once a decision, event, or connection exists you can change it — rename a gateway,
switch its type, retrigger an event, set or clear a branch condition — all through
the versioned, hash-chained governance write path (never a delete-and-redraw).

    python3 test_graphedit.py
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
    P, A = "CO.3.2.7", "role.ops.support_lead"
    s.enable_branching(P, A, "seed")

    # gateways
    gw = s.add_gateway(P, "exclusive", A, "fork", name="risk?")
    e = s.edit_gateway(gw["id"], {"name": "over threshold?", "type": "parallel"}, A, "rename + retype")
    check("edit_gateway renames + retypes, bumps version", e["name"] == "over threshold?" and e["type"] == "parallel" and e["version"] == 2)
    check("bad gateway type refused", rejects(lambda: s.edit_gateway(gw["id"], {"type": "maybe"}, A, "x"), "exclusive"))
    check("non-editable gateway field refused", rejects(lambda: s.edit_gateway(gw["id"], {"process_ref": "X"}, A, "x"), "not editable"))
    check("edit is live in the graph", cc.Graph().get("Gateway", gw["id"])["type"] == "parallel")

    # events
    ev = s.add_event(P, "intermediate", "timer", A, "sla", name="SLA", timer="P1D")
    e2 = s.edit_event(ev["id"], {"trigger": "message", "message_ref": "payment_received", "name": "on payment"}, A, "retrigger")
    check("edit_event retriggers timer->message + captures message_ref", e2["trigger"] == "message" and e2["message_ref"] == "payment_received" and e2["name"] == "on payment")
    check("bad event trigger refused", rejects(lambda: s.edit_event(ev["id"], {"trigger": "webhook"}, A, "x"), "trigger"))
    check("event edit is versioned", cc.Graph().get("Event", ev["id"])["version"] == 2)

    # flows: set then clear a condition
    f = s.add_flow(P, gw["id"], "CO.3.2.7.t4", A, "branch")
    check("a drawn flow starts without a condition", f.get("condition") is None)
    f2 = s.edit_flow(f["id"], {"condition": "risk_score > 0.7"}, A, "label the branch")
    check("edit_flow sets a branch condition", f2["condition"] == "risk_score > 0.7" and f2["version"] == 2)
    f3 = s.edit_flow(f["id"], {"condition": ""}, A, "clear it")
    check("edit_flow clears a condition back to none", f3["condition"] is None and f3["version"] == 3)
    check("non-editable flow field refused", rejects(lambda: s.edit_flow(f["id"], {"to_node": "CO.3.2.7.t1"}, A, "x"), "not editable"))

    # the whole thing is still a clean audit chain
    check("audit chain intact after all edits", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
