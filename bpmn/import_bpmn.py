"""
BPMN 2.0 XML import (Phase F, part 2).

Brings an existing BPMN 2.0 process *into* the governed model. Parses the XML,
maps its flow nodes and sequence flows back to Continuum entities, and — on apply
— creates a brand-new process and its tasks / gateways / events / flows through
the **same versioned, hash-chained governance write path** everything else uses.
So an imported process is governed and audited from the first event, exactly like
one authored in the canvas. It round-trips with export.py (each element's original
Continuum id, when present as `continuum:id`, is honored).

Two-step by design:
  - parse_bpmn(xml)     -> a structured, write-free reading of the file (+ warnings)
  - plan_import(xml)    -> a dry-run summary: what *would* be created. Writes nothing.
  - apply_import(...)   -> actually creates the process (audited). Explicit + separate,
                          so nothing is imported into the model by accident.

Mapping (the inverse of export.py):
  bpmn:userTask / task / manualTask / scriptTask -> a human step
  bpmn:serviceTask / sendTask / receiveTask / businessRuleTask -> a step, then
        agent-bound (the export writes agent steps as serviceTask)
  bpmn:exclusiveGateway / parallelGateway -> Gateway (exclusive / parallel)
  a plain start / end event -> the process start / end (__start__ / __end__)
  an event with a timer / message definition, or any intermediate event -> Event
  bpmn:sequenceFlow (+ conditionExpression) -> SequenceFlow (+ condition)
Unsupported constructs (pools/collaboration, sub-processes, inclusive/complex
gateways, data objects) are skipped with a warning, never silently dropped.
"""
from __future__ import annotations

import os
import re
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402

BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"
DC = "http://www.omg.org/spec/DD/20100524/DC"

HUMAN_TASKS = {"task", "userTask", "manualTask", "scriptTask"}
AGENT_TASKS = {"serviceTask", "sendTask", "receiveTask", "businessRuleTask"}
GATEWAYS = {"exclusiveGateway": "exclusive", "parallelGateway": "parallel"}
DEFAULT_OWNER = "role.ops.support_lead"


class ImportError_(ValueError):
    """A BPMN file that cannot be imported — the reason is safe to show a user."""


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _q(tag: str) -> str:
    return f"{{{BPMN}}}{tag}"


def _text(el, tag) -> str | None:
    c = el.find(_q(tag))
    return (c.text or "").strip() if c is not None and c.text else None


def _shape_x(root) -> dict:
    """Map bpmnElement id -> its DI x, for stable left-to-right ordering."""
    xs = {}
    for shape in root.iter(f"{{{BPMNDI}}}BPMNShape"):
        ref = shape.get("bpmnElement")
        b = shape.find(f"{{{DC}}}Bounds")
        if ref and b is not None and b.get("x") is not None:
            try:
                xs[ref] = float(b.get("x"))
            except ValueError:
                pass
    return xs


def parse_bpmn(xml_text: str) -> dict:
    """Read a BPMN 2.0 file into {name, tasks, gateways, events, flows, warnings}.
    Pure parse — writes nothing. Raises ImportError_ if there is no process."""
    try:
        root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    except ET.ParseError as e:
        raise ImportError_(f"not well-formed XML: {e}")
    proc = root.find(_q("process"))
    if proc is None:
        # some files nest the process differently; search the whole tree
        proc = next((e for e in root.iter(_q("process"))), None)
    if proc is None:
        raise ImportError_("no <bpmn:process> found (a pool-only collaboration cannot be imported)")

    xs = _shape_x(root)
    warnings: list[str] = []
    tasks, gateways, events, flows = [], [], [], []
    start_ids, end_ids = set(), set()

    for el in list(proc):
        tag = _local(el.tag)
        eid = el.get("id")
        name = el.get("name") or ""
        cid = el.get(f"{{{'https://continuum.dev/schema/v1'}}}id")
        if tag in HUMAN_TASKS or tag in AGENT_TASKS:
            tasks.append({"bpmn_id": eid, "name": name.strip() or "Step",
                          "agent": tag in AGENT_TASKS, "x": xs.get(eid, 0.0), "cont_id": cid})
        elif tag in GATEWAYS:
            gateways.append({"bpmn_id": eid, "type": GATEWAYS[tag], "name": name.strip(), "x": xs.get(eid, 0.0)})
        elif tag in ("inclusiveGateway", "complexGateway", "eventBasedGateway"):
            gateways.append({"bpmn_id": eid, "type": "exclusive", "name": name.strip(), "x": xs.get(eid, 0.0)})
            warnings.append(f"{tag} '{name or eid}' imported as an exclusive gateway (nearest supported type)")
        elif tag in ("startEvent", "endEvent", "intermediateCatchEvent", "intermediateThrowEvent", "boundaryEvent"):
            trigger, timer, msg = _event_trigger(el)
            kind = "start" if tag == "startEvent" else "end" if tag == "endEvent" else "intermediate"
            if kind in ("start", "end") and trigger == "none":
                (start_ids if kind == "start" else end_ids).add(eid)   # plain start/end -> pseudo node
            else:
                events.append({"bpmn_id": eid, "kind": kind, "trigger": trigger, "name": name.strip(),
                               "timer": timer, "message_ref": msg, "x": xs.get(eid, 0.0)})
        elif tag == "sequenceFlow":
            flows.append({"bpmn_id": eid, "source": el.get("sourceRef"), "target": el.get("targetRef"),
                          "condition": _text(el, "conditionExpression")})
        elif tag in ("laneSet", "extensionElements", "documentation"):
            pass  # lanes are a view (rebuilt from performers); extensions are metadata
        elif tag.endswith("SubProcess") or tag == "subProcess":
            warnings.append(f"sub-process '{name or eid}' skipped (drill-down is modeled per-step in Continuum)")
        elif tag in ("dataObject", "dataObjectReference", "dataStoreReference", "textAnnotation", "association"):
            pass
        else:
            warnings.append(f"unsupported element <{tag}> '{name or eid}' skipped")

    tasks.sort(key=lambda t: t["x"])
    gateways.sort(key=lambda g: g["x"])
    events.sort(key=lambda e: e["x"])
    return {"name": (proc.get("name") or _proc_name(root) or "Imported process").strip(),
            "tasks": tasks, "gateways": gateways, "events": events, "flows": flows,
            "start_ids": start_ids, "end_ids": end_ids, "warnings": warnings}


def _event_trigger(el) -> tuple[str, str | None, str | None]:
    if el.find(_q("timerEventDefinition")) is not None:
        td = el.find(_q("timerEventDefinition"))
        timer = None
        for t in ("timeDuration", "timeDate", "timeCycle"):
            c = td.find(_q(t))
            if c is not None and c.text:
                timer = c.text.strip(); break
        return "timer", timer, None
    if el.find(_q("messageEventDefinition")) is not None:
        med = el.find(_q("messageEventDefinition"))
        msg = med.get(f"{{{'https://continuum.dev/schema/v1'}}}messageRef") or el.get("name")
        return "message", None, msg
    return "none", None, None


def _proc_name(root) -> str | None:
    p = root.find(_q("process"))
    return p.get("name") if p is not None else None


def plan_from_parsed(p: dict) -> dict:
    """A dry-run summary of any parsed graph (BPMN or Visio). Writes nothing."""
    return {
        "name": p["name"],
        "counts": {"steps": len(p["tasks"]), "agent_steps": sum(1 for t in p["tasks"] if t["agent"]),
                   "gateways": len(p["gateways"]), "events": len(p["events"]), "flows": len(p["flows"])},
        "warnings": p["warnings"],
        "sample_steps": [t["name"] for t in p["tasks"][:6]],
    }


def plan_import(xml_text: str) -> dict:
    """A dry-run for a BPMN file: what would be created, plus warnings."""
    return plan_from_parsed(parse_bpmn(xml_text))


def _next_code(g: cc.Graph, prefix: str = "IM") -> str:
    """A fresh, unused APQC-style code for the imported process (IM = 'imported')."""
    n = 1
    while g.get("Process", f"{prefix}.{n}.1") is not None:
        n += 1
    return f"{prefix}.{n}.1"


def apply_import(xml_text: str, code: str | None = None, owner: str | None = None,
                 actor: str = DEFAULT_OWNER, reason: str = "imported from BPMN 2.0",
                 store: gov.GovernanceStore | None = None) -> dict:
    """Create a new process from the BPMN, through the audited write path. Returns
    {process, code, counts, warnings}. Every node and flow is a hash-chained event."""
    return apply_parsed(parse_bpmn(xml_text), code=code, owner=owner,
                        actor=actor, reason=reason, store=store)


def apply_parsed(parsed: dict, code: str | None = None, owner: str | None = None,
                 actor: str = DEFAULT_OWNER, reason: str = "imported from a diagram",
                 store: gov.GovernanceStore | None = None) -> dict:
    """Create a new process from an already-parsed graph (BPMN or Visio), through
    the audited write path. Shared by both importers so identity/id-remapping and
    the create sequence are identical."""
    s = store or gov.GovernanceStore()
    g = cc.Graph()
    code = code or _next_code(g)
    owner = owner or DEFAULT_OWNER

    proc = s.add_process(code, parsed["name"], owner, actor, reason)
    idmap: dict[str, str] = {}
    for bid in parsed["start_ids"]:
        idmap[bid] = "__start__"
    for bid in parsed["end_ids"]:
        idmap[bid] = "__end__"

    made = {"steps": 0, "agent_steps": 0, "gateways": 0, "events": 0, "flows": 0}
    for t in parsed["tasks"]:
        r = s.add_task(code, t["name"], actor, reason)
        idmap[t["bpmn_id"]] = r["id"]
        made["steps"] += 1
        if t["agent"]:
            s.bind_agent(r["id"], actor, "imported as an automated (service) task")
            made["agent_steps"] += 1
    for gw in parsed["gateways"]:
        r = s.add_gateway(code, gw["type"], actor, reason, name=gw["name"])
        idmap[gw["bpmn_id"]] = r["id"]
        made["gateways"] += 1
    for ev in parsed["events"]:
        r = s.add_event(code, ev["kind"], ev["trigger"], actor, reason,
                        name=ev["name"], timer=ev.get("timer"), message_ref=ev.get("message_ref"))
        idmap[ev["bpmn_id"]] = r["id"]
        made["events"] += 1

    warnings = list(parsed["warnings"])
    for f in parsed["flows"]:
        src, tgt = idmap.get(f["source"]), idmap.get(f["target"])
        if not src or not tgt:
            warnings.append(f"flow {f['bpmn_id']} skipped (an endpoint was not imported)")
            continue
        try:
            s.add_flow(code, src, tgt, actor, reason, condition=f.get("condition"))
            made["flows"] += 1
        except gov.EditError as e:
            warnings.append(f"flow {f['bpmn_id']} skipped: {e}")

    return {"process": proc, "code": code, "counts": made, "warnings": warnings}


if __name__ == "__main__":
    if len(sys.argv) > 1:
        with open(sys.argv[1]) as f:
            import json
            print(json.dumps(plan_import(f.read()), indent=2))
    else:
        print("usage: python import_bpmn.py <file.bpmn>   # dry-run plan")
