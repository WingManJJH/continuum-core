"""Phase F write-path tests — timer / message events (D31). Plain asserts.

Events are structural flow nodes (like gateways): created, validated, and audited
through the versioned, hash-chained governance write path.

    python3 test_event.py
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
    P = "FN.9.3.1"
    A = "role.ops.support_lead"

    # 0. the new locked type loads
    check("Graph knows the Event type", cc.Graph().all("Event") == [])

    # 1. create events of each trigger
    e1 = s.add_event(P, "start", "message", A, "kick off on inbound payment", name="payment received", message_ref="payment_received")
    check("add_event mints a versioned start/message node", e1["id"] == "FN.9.3.1.e1" and e1["kind"] == "start" and e1["trigger"] == "message" and e1["version"] == 1)
    check("message_ref is captured", e1["message_ref"] == "payment_received")
    e2 = s.add_event(P, "intermediate", "timer", A, "wait one day", name="cooling-off", timer="P1D")
    check("second event gets e2 + timer captured", e2["id"] == "FN.9.3.1.e2" and e2["timer"] == "P1D")

    # 2. validation guards
    check("bad kind refused", rejects(lambda: s.add_event(P, "middle", "timer", A, "x"), "kind"))
    check("bad trigger refused", rejects(lambda: s.add_event(P, "start", "webhook", A, "x"), "trigger"))
    check("event on unknown process refused", rejects(lambda: s.add_event("ZZ.9.9.9", "end", "none", A, "x"), "unknown process"))

    # 3. an event is a valid flow endpoint (schema pattern + _node_ok both widened)
    t1 = mapdata.all_maps()  # noqa: F841 — ensure graph loads
    f1 = s.add_flow(P, e1["id"], "FN.9.3.1.t1", A, "start-event into first step")
    check("a flow can run FROM an event", f1["from_node"] == "FN.9.3.1.e1" and f1["status"] == "active")
    f2 = s.add_flow(P, "FN.9.3.1.t1", e2["id"], A, "step into the timer")
    check("a flow can run TO an event", f2["to_node"] == "FN.9.3.1.e2")

    # 4. removing an event cascades its incident flows (all versioned)
    s.remove_event(e2["id"], A, "drop the cooling-off wait")
    g = cc.Graph()
    check("removed event is deprecated", g.get("Event", e2["id"])["status"] == "deprecated")
    active_flow_ids = [f["id"] for f in g.all("SequenceFlow") if f["status"] == "active" and f["process_ref"] == P]
    check("the flow into the removed event was retired too", f2["id"] not in active_flow_ids)
    check("the unrelated flow survived", f1["id"] in active_flow_ids)

    # 5. mapdata surfaces active events for the canvas + export
    m = next(x for x in mapdata.all_maps(g) if x["id"] == P)
    ev_ids = [e["id"] for e in m["events"]]
    check("mapdata lists the surviving event, not the removed one", e1["id"] in ev_ids and e2["id"] not in ev_ids)
    check("event payload carries kind + trigger", all("kind" in e and "trigger" in e for e in m["events"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
