"""BPMN 2.0 import tests (D32). Plain asserts.

The headline test is a real round-trip: build a branching process, export it to
BPMN, import that XML back as a NEW process, and confirm the shape is reconstructed
(steps, agent binding, gateway, event, flows) — all through the audited write path.

    python3 test_import.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import mapdata  # noqa: E402
import export as bpmn  # noqa: E402
import import_bpmn as imp  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def src_map(P):
    return next(x for x in mapdata.all_maps(cc.Graph()) if x["id"] == P)


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    P = "CO.3.2.7"   # has an agent-bound step (t3) to exercise the serviceTask round-trip
    A = "role.ops.support_lead"

    # build a branching graph: gateway + conditioned branch + a timer event
    s.enable_branching(P, A, "seed explicit flow")
    gw = s.add_gateway(P, "exclusive", A, "risk fork", name="risk?")
    s.add_flow(P, "CO.3.2.7.t2", gw["id"], A, "into the fork")
    s.add_flow(P, gw["id"], "CO.3.2.7.t4", A, "high-risk branch", condition="risk_score > 0.7")
    ev = s.add_event(P, "intermediate", "timer", A, "SLA", name="24h SLA", timer="PT24H")
    s.add_flow(P, "CO.3.2.7.t3", ev["id"], A, "into the timer")

    src = src_map(P)
    xml = bpmn.export_process(P)

    # 1. parse / dry-run reads the file without writing
    before = os.path.getsize(cc.EDITS_LOG)
    plan = imp.plan_import(xml)
    check("plan_import reads the process name", plan["name"] == src["name"])
    check("plan counts steps + gateways + events + flows",
          plan["counts"]["steps"] == len(src["tasks"]) and plan["counts"]["gateways"] == len(src["gateways"])
          and plan["counts"]["events"] == len(src["events"]) and plan["counts"]["flows"] == len(src["flows"]))
    check("plan spots the agent (service) task", plan["counts"]["agent_steps"] >= 1)
    check("dry-run writes NOTHING to the audit log", os.path.getsize(cc.EDITS_LOG) == before)

    # 2. apply: a new process, reconstructed, through the audited write path
    res = imp.apply_import(xml, code="IM.1.1", actor=A, store=s)
    check("apply mints a fresh imported process", res["code"] == "IM.1.1")
    g = cc.Graph()
    check("the imported process now exists in the graph", g.get("Process", "IM.1.1") is not None)
    new = src_map("IM.1.1")
    check("same number of steps round-tripped", len(new["tasks"]) == len(src["tasks"]))
    check("same number of gateways", len(new["gateways"]) == len(src["gateways"]))
    check("same number of events (the timer)", len(new["events"]) == len(src["events"]))
    check("the timer event carries its schedule", any(e["trigger"] == "timer" and e["timer"] == "PT24H" for e in new["events"]))
    check("same number of flows", len(new["flows"]) == len(src["flows"]))
    check("the service task came back agent-bound", any(t["agents"] for t in new["tasks"]))
    check("a branch condition survived the round-trip", any(f.get("condition") == "risk_score > 0.7" for f in new["flows"]))

    # 3. the import is genuinely audited (hash chain still intact after all those writes)
    check("audit chain intact after import", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    # 4. a re-export of the imported process is itself well-formed (double round-trip)
    import xml.etree.ElementTree as ET
    ET.fromstring(bpmn.export_process("IM.1.1"))
    check("the imported process re-exports to well-formed BPMN", True)

    # 5. robustness: no <process> is refused; unsupported elements warn, not crash
    try:
        imp.parse_bpmn("<bpmn:definitions xmlns:bpmn='%s'/>" % imp.BPMN); ok = False
    except imp.ImportError_:
        ok = True
    check("a file with no process is refused", ok)
    weird = ("<bpmn:definitions xmlns:bpmn='%s'><bpmn:process id='P'>"
             "<bpmn:inclusiveGateway id='g1' name='maybe'/>"
             "<bpmn:dataObject id='d1'/></bpmn:process></bpmn:definitions>") % imp.BPMN
    parsed = imp.parse_bpmn(weird)
    check("inclusive gateway imported as exclusive + warned",
          len(parsed["gateways"]) == 1 and parsed["gateways"][0]["type"] == "exclusive"
          and any("inclusiveGateway" in w for w in parsed["warnings"]))

    # This test creates a persistent NEW process (IM.1.1) in the shared edit log.
    # Leave the log at the clean seed baseline so order-independent reader tests
    # (e.g. ask/test_agent) still see the 8-process seed.
    cc.reset_log(cc.EDITS_LOG)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
