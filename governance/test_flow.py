"""Phase B write-path tests — gateways + sequence flows (D27). Plain asserts.

Exercises the explicit process-flow graph on top of the linear task model, all
through the versioned, hash-chained governance write path.

    python3 test_flow.py
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
    P = "CO.3.2.7"
    A = "role.ops.support_lead"

    # 0. new entity types load in the graph
    g = cc.Graph()
    check("Graph knows Gateway + SequenceFlow", g.all("Gateway") == [] and g.all("SequenceFlow") == [])

    # 1. gateways
    gw = s.add_gateway(P, "exclusive", A, "risk fork", name="risk?")
    check("add_gateway makes a versioned exclusive node", gw["id"] == "CO.3.2.7.g1" and gw["type"] == "exclusive" and gw["version"] == 1)
    gw2 = s.add_gateway(P, "parallel", A, "parallel")
    check("second gateway gets g2", gw2["id"] == "CO.3.2.7.g2")
    check("bad gateway type refused", rejects(lambda: s.add_gateway(P, "maybe", A, "x"), "exclusive"))
    check("gateway on unknown process refused", rejects(lambda: s.add_gateway("ZZ.9.9.9", "exclusive", A, "x"), "unknown process"))

    # 2. flows: valid + all the guards
    f1 = s.add_flow(P, "__start__", "CO.3.2.7.t1", A, "start into t1")
    check("add_flow makes a versioned edge", f1["id"] == "CO.3.2.7.f1" and f1["from_node"] == "__start__")
    f2 = s.add_flow(P, "CO.3.2.7.t1", gw["id"], A, "t1 to gateway")
    fc = s.add_flow(P, gw["id"], "CO.3.2.7.t3", A, "branch", condition="risk_score > 0.7")
    check("flow out of a gateway carries a condition", fc["condition"] == "risk_score > 0.7")
    check("self-loop refused", rejects(lambda: s.add_flow(P, "CO.3.2.7.t1", "CO.3.2.7.t1", A, "x"), "itself"))
    check("wrong-direction (into __start__) refused", rejects(lambda: s.add_flow(P, "CO.3.2.7.t1", "__start__", A, "x"), "start"))
    check("unknown target node refused", rejects(lambda: s.add_flow(P, "CO.3.2.7.t1", "CO.3.2.7.t99", A, "x"), "unknown target"))
    check("cross-process endpoint refused", rejects(lambda: s.add_flow(P, "CO.3.2.7.t1", "FN.9.3.1.t1", A, "x"), "unknown target"))
    check("duplicate flow refused", rejects(lambda: s.add_flow(P, "__start__", "CO.3.2.7.t1", A, "x"), "already exists"))

    # 3. mapdata surfaces the explicit graph
    m = next(x for x in mapdata.all_maps() if x["id"] == P)
    check("mapdata marks the process explicit", m["explicit"] is True)
    check("mapdata lists gateways + flows", len(m["gateways"]) == 2 and len(m["flows"]) == 3)
    check("gateway condition surfaces on its flow", any(fl["condition"] == "risk_score > 0.7" for fl in m["flows"]))

    # 4. removing a gateway cascades its flows (no dangling edges)
    s.remove_gateway(gw["id"], A, "drop the fork")
    m = next(x for x in mapdata.all_maps() if x["id"] == P)
    check("removed gateway is gone", not any(x["id"] == gw["id"] for x in m["gateways"]))
    check("its incident flows were cascaded", all(gw["id"] not in (fl["from"], fl["to"]) for fl in m["flows"]))
    check("only the start->t1 flow remains", len(m["flows"]) == 1 and m["flows"][0]["from"] == "__start__")

    # 5. remove a flow directly
    s.remove_flow(m["flows"][0]["id"], A, "clear it")
    m = next(x for x in mapdata.all_maps() if x["id"] == P)
    check("flow removed -> no explicit flows -> implicit again", m["explicit"] is False and m["flows"] == [])

    # 6. enable_branching seeds an editable graph from the linear sequence
    seeded = s.enable_branching(P, A, "make it editable")
    m = next(x for x in mapdata.all_maps() if x["id"] == P)
    check("enable_branching seeds start->...->end from seq", len(seeded) == len(m["tasks"]) + 1)
    check("seeded chain starts at __start__ and ends at __end__",
          any(fl["from"] == "__start__" for fl in m["flows"]) and any(fl["to"] == "__end__" for fl in m["flows"]))
    check("enable_branching refused when already explicit", rejects(lambda: s.enable_branching(P, A, "again"), "already has"))

    # 7. everything above is on the hash-chained audit trail
    check("audit chain intact after flow edits", cc.verify_log(cc.EDITS_LOG)["ok"])

    # 8. required reason is enforced (ISO 9001 §7.5) like every other edit
    check("empty reason refused", rejects(lambda: s.add_gateway(P, "exclusive", A, "  "), ""))

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
