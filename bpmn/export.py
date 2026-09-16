"""
BPMN 2.0 XML export (Phase F).

Serializes a Continuum process — its tasks, gateways, timer/message events, and
sequence flows — to standards-compliant **BPMN 2.0 XML**, including a BPMNDI
diagram-interchange block (computed left-to-right layout) so the file opens *with
a drawing* in Camunda Modeler, bpmn.io, Signavio, or any BPMN tool.

Why this matters (Core Model §03 / §10): a process modeled in Continuum is not
locked in. It round-trips through the industry interchange format, so an
organization can bring existing BPMN in (see import_bpmn.py) and take Continuum
models out — the governed model is the source of truth, BPMN is a view of it.

Mapping decisions:
  - agent-bound task  -> bpmn:serviceTask   (it runs automatically)
  - human task        -> bpmn:userTask
  - exclusive gateway -> bpmn:exclusiveGateway ; parallel -> bpmn:parallelGateway
  - event kind        -> start/intermediateCatch/end ; trigger -> timer/message
                         event definition
  - the process start/end (__start__/__end__) -> a plain start / end event
  - condition on a flow -> bpmn:conditionExpression
  - performing role   -> a bpmn:lane in the process laneSet
The original Continuum ids are preserved on every element as `continuum:id`, so an
export can be re-imported without losing identity.

Read-only: this reads the graph and returns a string; it writes nothing.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
import continuum_core as cc  # noqa: E402
from mapdata import all_maps  # noqa: E402

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"
DI = "http://www.omg.org/spec/DD/20100524/DI"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
CONTINUUM = "https://continuum.dev/schema/v1"
for pfx, uri in [("bpmn", BPMN), ("bpmndi", BPMNDI), ("dc", DC), ("di", DI), ("xsi", XSI), ("continuum", CONTINUUM)]:
    ET.register_namespace(pfx, uri)

# node sizes (BPMN convention) and layout spacing
SZ = {"task": (110, 74), "gateway": (50, 50), "event": (36, 36)}
COLSTEP, ROWSTEP, MARGIN = 170, 110, 50


def _nid(node: str) -> str:
    """A BPMN-safe element id for a Continuum node id / pseudo node."""
    if node == "__start__":
        return "StartEvent_1"
    if node == "__end__":
        return "EndEvent_1"
    return "n_" + re.sub(r"[^A-Za-z0-9]", "_", node)


def _q(ns: str, tag: str) -> str:
    return f"{{{ns}}}{tag}"


def _build_nodes(m: dict) -> tuple[dict, list]:
    """Return (nodes, edges). nodes[key] = descriptor; key is the Continuum node id
    or a pseudo '__start__'/'__end__'. edges = list of {id, source, target, condition}."""
    nodes: dict[str, dict] = {}
    tasks = {t["id"]: t for t in m["tasks"]}
    gateways = {g["id"]: g for g in m.get("gateways", [])}
    events = {e["id"]: e for e in m.get("events", [])}

    def task_desc(t):
        auto = bool(t["agents"])
        return {"key": t["id"], "bpmn_id": _nid(t["id"]),
                "el": "serviceTask" if auto else "userTask", "cat": "task",
                "name": t["name"], "role": (t["roles"][0] if t["roles"] else ("__agent__" if auto else "__none__")),
                "cont_id": t["id"], "seq": t["seq"]}

    def gw_desc(g):
        return {"key": g["id"], "bpmn_id": _nid(g["id"]),
                "el": "parallelGateway" if g["type"] == "parallel" else "exclusiveGateway",
                "cat": "gateway", "name": g.get("name", ""), "cont_id": g["id"]}

    def ev_desc(e):
        el = {"start": "startEvent", "intermediate": "intermediateCatchEvent", "end": "endEvent"}[e["kind"]]
        return {"key": e["id"], "bpmn_id": _nid(e["id"]), "el": el, "cat": "event",
                "name": e.get("name", ""), "trigger": e.get("trigger", "none"),
                "timer": e.get("timer"), "message_ref": e.get("message_ref"), "cont_id": e["id"]}

    if m.get("explicit") and m.get("flows"):
        edges = [{"id": _nid(f["id"]), "source": _nid(f["from"]), "target": _nid(f["to"]),
                  "condition": f.get("condition"), "cont_id": f["id"]} for f in m["flows"]]
        referenced = set()
        for f in m["flows"]:
            referenced.add(f["from"]); referenced.add(f["to"])
        # every task/gateway/event, plus the pseudo start/end if a flow uses them
        for t in m["tasks"]:
            nodes[t["id"]] = task_desc(t)
        for g in m.get("gateways", []):
            nodes[g["id"]] = gw_desc(g)
        for e in m.get("events", []):
            nodes[e["id"]] = ev_desc(e)
        if "__start__" in referenced:
            nodes["__start__"] = {"key": "__start__", "bpmn_id": "StartEvent_1", "el": "startEvent",
                                  "cat": "event", "name": "start", "trigger": "none"}
        if "__end__" in referenced:
            nodes["__end__"] = {"key": "__end__", "bpmn_id": "EndEvent_1", "el": "endEvent",
                                "cat": "event", "name": "end", "trigger": "none"}
        return nodes, edges

    # linear: synthesize start -> tasks(seq) -> end
    seq = sorted(m["tasks"], key=lambda t: t["seq"])
    nodes["__start__"] = {"key": "__start__", "bpmn_id": "StartEvent_1", "el": "startEvent",
                          "cat": "event", "name": "start", "trigger": "none"}
    for t in seq:
        nodes[t["id"]] = task_desc(t)
    nodes["__end__"] = {"key": "__end__", "bpmn_id": "EndEvent_1", "el": "endEvent",
                        "cat": "event", "name": "end", "trigger": "none"}
    chain = ["__start__"] + [t["id"] for t in seq] + ["__end__"]
    edges = [{"id": "flow_%d" % (i + 1), "source": _nid(chain[i]), "target": _nid(chain[i + 1]),
              "condition": None, "cont_id": None} for i in range(len(chain) - 1)]
    return nodes, edges


def _layout(nodes: dict, edges: list) -> dict:
    """Longest-path left-to-right layering → each bpmn_id gets center (cx, cy) and size."""
    by_bpmn = {n["bpmn_id"]: n for n in nodes.values()}
    depth = {bid: 0 for bid in by_bpmn}
    indeg = {bid: 0 for bid in by_bpmn}
    for e in edges:
        if e["source"] in indeg and e["target"] in indeg:
            indeg[e["target"]] += 1
    for _ in range(len(by_bpmn) + 2):
        for e in edges:
            if e["source"] in depth and e["target"] in depth and depth[e["target"]] <= depth[e["source"]]:
                depth[e["target"]] = depth[e["source"]] + 1
    cols: dict[int, list] = {}
    for bid in sorted(by_bpmn, key=lambda b: (depth[b], b)):
        cols.setdefault(depth[bid], []).append(bid)
    geo = {}
    for d, ids in cols.items():
        for r, bid in enumerate(ids):
            n = by_bpmn[bid]
            w, h = SZ[n["cat"]]
            cx = MARGIN + d * COLSTEP + w / 2
            cy = MARGIN + r * ROWSTEP + h / 2 + 40
            geo[bid] = {"cx": cx, "cy": cy, "w": w, "h": h}
    return geo


def process_to_bpmn(m: dict) -> str:
    """Serialize one mapdata process dict to BPMN 2.0 XML (pretty-printed)."""
    nodes, edges = _build_nodes(m)
    geo = _layout(nodes, edges)
    proc_id = "Process_" + re.sub(r"[^A-Za-z0-9]", "_", m["id"])

    defs = ET.Element(_q(BPMN, "definitions"), {
        "id": "Definitions_" + re.sub(r"[^A-Za-z0-9]", "_", m["id"]),
        "targetNamespace": "https://continuum.dev/bpmn",
        _q(CONTINUUM, "model"): m["id"],
    })
    proc = ET.SubElement(defs, _q(BPMN, "process"),
                         {"id": proc_id, "name": m["name"], "isExecutable": "false",
                          _q(CONTINUUM, "id"): m["id"], _q(CONTINUUM, "owner"): m.get("owner", "")})

    # laneSet — one lane per performing role (tasks only)
    lanes: dict[str, list] = {}
    for n in nodes.values():
        if n["cat"] == "task":
            lanes.setdefault(n["role"], []).append(n["bpmn_id"])
    if lanes:
        lane_set = ET.SubElement(proc, _q(BPMN, "laneSet"), {"id": "LaneSet_" + proc_id})
        for role, ids in lanes.items():
            label = "Automated (agent)" if role == "__agent__" else "Unassigned" if role == "__none__" else role
            lane = ET.SubElement(lane_set, _q(BPMN, "lane"),
                                 {"id": "Lane_" + re.sub(r"[^A-Za-z0-9]", "_", role), "name": label})
            for bid in ids:
                ref = ET.SubElement(lane, _q(BPMN, "flowNodeRef"))
                ref.text = bid

    # flow nodes
    incoming: dict[str, list] = {}
    outgoing: dict[str, list] = {}
    for e in edges:
        outgoing.setdefault(e["source"], []).append(e["id"])
        incoming.setdefault(e["target"], []).append(e["id"])
    for n in sorted(nodes.values(), key=lambda x: x["bpmn_id"]):
        attrs = {"id": n["bpmn_id"]}
        if n.get("name"):
            attrs["name"] = n["name"]
        if n.get("cont_id"):
            attrs[_q(CONTINUUM, "id")] = n["cont_id"]
        el = ET.SubElement(proc, _q(BPMN, n["el"]), attrs)
        for fid in incoming.get(n["bpmn_id"], []):
            ET.SubElement(el, _q(BPMN, "incoming")).text = fid
        for fid in outgoing.get(n["bpmn_id"], []):
            ET.SubElement(el, _q(BPMN, "outgoing")).text = fid
        # event definitions (timer / message)
        if n["cat"] == "event" and n.get("trigger") in ("timer", "message"):
            if n["trigger"] == "timer":
                td = ET.SubElement(el, _q(BPMN, "timerEventDefinition"))
                dur = ET.SubElement(td, _q(BPMN, "timeDuration"),
                                    {_q(XSI, "type"): "bpmn:tFormalExpression"})
                dur.text = n.get("timer") or ""
            else:
                med = ET.SubElement(el, _q(BPMN, "messageEventDefinition"))
                if n.get("message_ref"):
                    med.set(_q(CONTINUUM, "messageRef"), n["message_ref"])

    # sequence flows
    for e in edges:
        sf = ET.SubElement(proc, _q(BPMN, "sequenceFlow"),
                           {"id": e["id"], "sourceRef": e["source"], "targetRef": e["target"]})
        if e.get("cont_id"):
            sf.set(_q(CONTINUUM, "id"), e["cont_id"])
        if e.get("condition"):
            ce = ET.SubElement(sf, _q(BPMN, "conditionExpression"),
                               {_q(XSI, "type"): "bpmn:tFormalExpression"})
            ce.text = e["condition"]

    # BPMNDI — diagram interchange (so the file renders with layout)
    diagram = ET.SubElement(defs, _q(BPMNDI, "BPMNDiagram"), {"id": "Diagram_" + proc_id})
    plane = ET.SubElement(diagram, _q(BPMNDI, "BPMNPlane"),
                          {"id": "Plane_" + proc_id, "bpmnElement": proc_id})
    for n in nodes.values():
        g = geo.get(n["bpmn_id"])
        if not g:
            continue
        shape = ET.SubElement(plane, _q(BPMNDI, "BPMNShape"),
                              {"id": n["bpmn_id"] + "_di", "bpmnElement": n["bpmn_id"]})
        ET.SubElement(shape, _q(DC, "Bounds"),
                      {"x": _fmt(g["cx"] - g["w"] / 2), "y": _fmt(g["cy"] - g["h"] / 2),
                       "width": _fmt(g["w"]), "height": _fmt(g["h"])})
    for e in edges:
        A, B = geo.get(e["source"]), geo.get(e["target"])
        if not A or not B:
            continue
        edge = ET.SubElement(plane, _q(BPMNDI, "BPMNEdge"),
                             {"id": e["id"] + "_di", "bpmnElement": e["id"]})
        ET.SubElement(edge, _q(DI, "waypoint"), {"x": _fmt(A["cx"] + A["w"] / 2), "y": _fmt(A["cy"])})
        ET.SubElement(edge, _q(DI, "waypoint"), {"x": _fmt(B["cx"] - B["w"] / 2), "y": _fmt(B["cy"])})

    ET.indent(defs, space="  ")
    xml = ET.tostring(defs, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + xml + "\n"


def _fmt(v: float) -> str:
    return str(int(round(v)))


def export_process(process_id: str, g: cc.Graph | None = None) -> str:
    g = g or cc.Graph()
    m = next((x for x in all_maps(g) if x["id"] == process_id), None)
    if m is None:
        raise ValueError(f"unknown process {process_id}")
    return process_to_bpmn(m)


if __name__ == "__main__":
    pid = sys.argv[1] if len(sys.argv) > 1 else "CO.3.2.7"
    print(export_process(pid))
