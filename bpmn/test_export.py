"""BPMN 2.0 export tests (D31). Plain asserts.

Builds a real branching process (gateway + conditioned flow + timer event) through
the governance write path, exports it, and checks the BPMN is well-formed and
carries the elements a BPMN tool needs to render and re-import it.

    python3 test_export.py
"""
from __future__ import annotations

import os
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import export as bpmn  # noqa: E402

NS = {"bpmn": "http://www.omg.org/spec/BPMN/20100524/MODEL",
      "bpmndi": "http://www.omg.org/spec/BPMN/20100524/DI",
      "dc": "http://www.omg.org/spec/DD/20100524/DC",
      "continuum": "https://continuum.dev/schema/v1"}

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    P = "CO.3.2.7"
    A = "role.ops.support_lead"

    # linear export first (no explicit flows) — start -> tasks -> end synthesized
    xml_lin = bpmn.export_process(P)
    root = ET.fromstring(xml_lin)
    check("root is bpmn:definitions", root.tag == "{%s}definitions" % NS["bpmn"])
    proc = root.find("bpmn:process", NS)
    check("linear export synthesizes one start + one end event",
          len(proc.findall("bpmn:startEvent", NS)) == 1 and len(proc.findall("bpmn:endEvent", NS)) == 1)
    check("agent-bound step becomes a serviceTask", len(proc.findall("bpmn:serviceTask", NS)) >= 1)
    check("human steps become userTasks", len(proc.findall("bpmn:userTask", NS)) >= 2)
    check("laneSet groups nodes by performing role", proc.find("bpmn:laneSet", NS) is not None)
    check("original Continuum id preserved on a task",
          any(t.get("{%s}id" % NS["continuum"]) for t in proc.findall("bpmn:userTask", NS)))

    # now make it a branching graph with a gateway, a conditioned flow, and a timer
    s.enable_branching(P, A, "seed explicit flow")
    gw = s.add_gateway(P, "exclusive", A, "risk fork", name="risk?")
    s.add_flow(P, "CO.3.2.7.t2", gw["id"], A, "into the fork")
    s.add_flow(P, gw["id"], "CO.3.2.7.t4", A, "high-risk branch", condition="risk_score > 0.7")
    ev = s.add_event(P, "intermediate", "timer", A, "SLA timer", name="24h SLA", timer="PT24H")
    s.add_flow(P, "CO.3.2.7.t3", ev["id"], A, "step into the timer")

    xml = bpmn.export_process(P)
    root = ET.fromstring(xml)
    proc = root.find("bpmn:process", NS)
    check("explicit export emits an exclusiveGateway", proc.find("bpmn:exclusiveGateway", NS) is not None)
    check("a timer event carries a timerEventDefinition",
          any(e.find("bpmn:timerEventDefinition", NS) is not None for e in proc.findall("bpmn:intermediateCatchEvent", NS)))
    conds = [c.text for sf in proc.findall("bpmn:sequenceFlow", NS) for c in sf.findall("bpmn:conditionExpression", NS)]
    check("a conditioned flow becomes a conditionExpression", "risk_score > 0.7" in conds)

    # referential integrity: every flow endpoint is a declared node id
    node_ids = set()
    for tag in ("startEvent", "endEvent", "task", "userTask", "serviceTask",
                "exclusiveGateway", "parallelGateway", "intermediateCatchEvent"):
        for n in proc.findall("bpmn:" + tag, NS):
            node_ids.add(n.get("id"))
    flows = proc.findall("bpmn:sequenceFlow", NS)
    dangling = [f.get("id") for f in flows if f.get("sourceRef") not in node_ids or f.get("targetRef") not in node_ids]
    check("no sequence flow dangles (every endpoint is a real node)", dangling == [])

    # BPMNDI: a shape per node and an edge per flow, so it renders in a BPMN tool
    plane = root.find("bpmndi:BPMNDiagram/bpmndi:BPMNPlane", NS)
    shapes = plane.findall("bpmndi:BPMNShape", NS)
    edges = plane.findall("bpmndi:BPMNEdge", NS)
    check("DI has a shape for every flow node", len(shapes) == len(node_ids))
    check("DI has an edge for every sequence flow", len(edges) == len(flows))
    check("every shape has bounds", all(sh.find("dc:Bounds", NS) is not None for sh in shapes))

    # unknown process refused
    try:
        bpmn.export_process("ZZ.9.9.9"); ok = False
    except ValueError:
        ok = True
    check("exporting an unknown process is refused", ok)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
