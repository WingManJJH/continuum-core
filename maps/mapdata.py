"""
Process-map data — Core Model §03 "Canvas View" (first slice).

Assembles, from the one graph, everything a BPMN-style process map needs: each
process's ordered tasks, who performs each (human role and/or agent), the
effective guardrail per task, its escalation branch, task-level overrides, and the
process header (owner, guardrail version, KPIs, linked risk). Rendered visually by
maps/static (a diagram), served by maps/app.py. Read-only — the same source of
truth the agent, governance, and dashboard layers all read.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import layout  # decorative node positions, kept out of the governed model  # noqa: E402


def all_maps(g: cc.Graph | None = None) -> list[dict]:
    g = g or cc.Graph()
    out = []
    for p in sorted(g.all("Process"), key=lambda x: x["id"]):
        pgr = g.get("GuardrailPolicy", p.get("guardrail_ref"))
        risks = [{"id": r["id"], "risk": r["risk"]}
                 for r in (g.get("RiskControl", rr) for rr in p.get("risk_refs", [])) if r]
        tasks = []
        for t in sorted((t for t in g.all("Task")
                         if t["process_ref"] == p["id"] and t["status"] == "active"),
                        key=lambda t: t["seq"]):
            gr, pinned = g.effective_guardrail(t["id"])
            # the full effective guardrail, trimmed to what the in-canvas editor
            # can change (matches the governance write path) — None if unguarded.
            gfull = None if not gr else {
                "id": gr["id"], "version": gr["version"],
                "allowed_actions": gr["allowed_actions"], "forbidden_actions": gr["forbidden_actions"],
                "escalate_if": gr.get("escalate_if"), "data_scope": gr["data_scope"],
                "rate_limit": gr.get("rate_limit"), "escalation_path": gr["escalation_path"],
                "audit_requirement": gr["audit_requirement"],
            }
            tasks.append({
                "id": t["id"], "seq": t["seq"], "name": t["name"],
                "roles": [w for w in t["performed_by"] if w.startswith("role.")],
                "agents": [w for w in t["performed_by"] if w.startswith("agent.")],
                "override": bool(t.get("guardrail_ref")),
                "guardrail": pinned,
                "escalate_if": gr.get("escalate_if") if gr else None,
                "escalation_path": gr.get("escalation_path") if gr else None,
                "allow": gr.get("allowed_actions", []) if gr else [],
                "deny": gr.get("forbidden_actions", []) if gr else [],
                "inputs": t.get("inputs", []), "outputs": t.get("outputs", []),
                "data_scope": t.get("data_scope", []), "kpi_refs": t.get("kpi_refs", []),
                "subprocess": t.get("subprocess_ref"),
                "guardrail_full": gfull,
            })
        gateways = [{"id": x["id"], "type": x["type"], "name": x.get("name", "")}
                    for x in sorted((x for x in g.all("Gateway")
                                     if x["process_ref"] == p["id"] and x["status"] == "active"),
                                    key=lambda x: x["id"])]
        flows = [{"id": f["id"], "from": f["from_node"], "to": f["to_node"],
                  "condition": f.get("condition")}
                 for f in sorted((f for f in g.all("SequenceFlow")
                                  if f["process_ref"] == p["id"] and f["status"] == "active"),
                                 key=lambda f: f["id"])]
        events = [{"id": x["id"], "kind": x["kind"], "trigger": x["trigger"],
                   "name": x.get("name", ""), "timer": x.get("timer"),
                   "message_ref": x.get("message_ref")}
                  for x in sorted((x for x in g.all("Event")
                                   if x["process_ref"] == p["id"] and x["status"] == "active"),
                                  key=lambda x: x["id"])]
        out.append({
            "id": p["id"], "name": p["name"], "owner": p["owner_role"],
            "guardrail": f"{p['guardrail_ref']}.v{pgr['version']}" if pgr else None,
            "kpis": p.get("kpi_refs", []), "risks": risks, "tasks": tasks,
            "gateways": gateways, "flows": flows, "events": events, "explicit": bool(flows),
            "parent_ref": p.get("parent_ref"), "objective_refs": p.get("objective_refs", []),
            "custom": p.get("custom", {}), "maturity_score": p.get("maturity_score"),
            "layout": layout.load_process(p["id"]),  # {node_id: {x,y}} — decorative
        })
    return out


DOMAIN_NAMES = {
    "CO": "Customer Operations", "FN": "Finance", "SC": "Supply Chain",
    "MS": "Marketing & Sales", "IT": "Information Technology",
    "PD": "Product Development", "HR": "Human Resources", "SV": "Strategy",
}


def _proc_card(g: cc.Graph, p: dict) -> dict:
    tasks = [t for t in g.all("Task") if t["process_ref"] == p["id"] and t["status"] == "active"]
    agent_steps = sum(1 for t in tasks if any(str(w).startswith("agent.") for w in t.get("performed_by", [])))
    gr = g.get("GuardrailPolicy", p.get("guardrail_ref"))
    return {"id": p["id"], "name": p["name"], "owner": p["owner_role"], "steps": len(tasks),
            "agent_steps": agent_steps, "reviewed": bool(gr and gr.get("review", {}).get("reviewed_by")),
            "risks": len(p.get("risk_refs", [])), "kpis": p.get("kpi_refs", []),
            "objective_refs": p.get("objective_refs", []), "custom": p.get("custom", {}),
            "parent_ref": p.get("parent_ref"), "maturity_score": p.get("maturity_score")}


def architecture(g: cc.Graph | None = None) -> dict:
    """The L1–L5 process hierarchy: ProcessGroups nested by parent, each with the
    leaf Processes that roll up to it. Feeds the management Architecture view and the
    master-data panels. Read-only, from the one graph."""
    g = g or cc.Graph()
    groups = [x for x in g.all("ProcessGroup") if x["status"] == "active"]
    procs = [p for p in g.all("Process") if p["status"] == "active"]
    by_id = {x["id"]: x for x in groups}
    children = {}
    for x in groups:
        children.setdefault(x.get("parent_ref"), []).append(x["id"])
    procs_of = {}
    for p in procs:
        procs_of.setdefault(p.get("parent_ref"), []).append(p)

    def node(gid: str) -> dict:
        x = by_id[gid]
        return {"id": gid, "name": x["name"], "level": x["level"], "owner_role": x.get("owner_role"),
                "objective_refs": x.get("objective_refs", []), "description": x.get("description", ""),
                "custom": x.get("custom", {}),
                "children": [node(c) for c in sorted(children.get(gid, []))],
                "processes": [_proc_card(g, p) for p in sorted(procs_of.get(gid, []), key=lambda p: p["id"])]}

    roots = [node(gid) for gid in sorted(children.get(None, []))]
    known = set(by_id)
    orphans = [_proc_card(g, p) for p in sorted(procs, key=lambda p: p["id"])
               if not p.get("parent_ref") or p.get("parent_ref") not in known]
    flat = [{"id": x["id"], "name": x["name"], "level": x["level"], "parent_ref": x.get("parent_ref"),
             "owner_role": x.get("owner_role"), "objective_refs": x.get("objective_refs", []),
             "description": x.get("description", ""), "custom": x.get("custom", {}),
             "process_count": len(procs_of.get(x["id"], []))}
            for x in sorted(groups, key=lambda x: (x["level"], x["id"]))]
    return {"roots": roots, "orphans": orphans, "groups": flat, "process_total": len(procs)}


def roles(g: cc.Graph | None = None) -> list[dict]:
    """The role master data (§02 HumanRole), each annotated with where it is used —
    owner of a process, performer of a step, a guardrail's escalation path, or an
    objective owner. Read-only, from the one graph; feeds the manage-roles panel and
    the click-through role drawer."""
    g = g or cc.Graph()
    procs = [p for p in g.all("Process") if p["status"] == "active"]
    tasks = [t for t in g.all("Task") if t["status"] == "active"]
    grs = [x for x in g.all("GuardrailPolicy") if x.get("status") == "active"]
    objs = g.all("StrategicObjective")
    out = []
    for r in sorted((x for x in g.all("HumanRole") if x["status"] == "active"), key=lambda x: x["id"]):
        rid = r["id"]
        owner = [p["id"] for p in procs if p.get("owner_role") == rid]
        perf_tasks = [t["id"] for t in tasks if rid in t.get("performed_by", [])]
        perf_procs = sorted({t["process_ref"] for t in tasks if rid in t.get("performed_by", [])})
        esc = [gr["id"] for gr in grs if gr.get("escalation_path") == rid]
        obj = [o["id"] for o in objs if o.get("owner_role") == rid]
        count = len(owner) + len(perf_tasks) + len(esc) + len(obj)
        out.append({
            "id": rid, "name": r.get("name", rid), "raci": r.get("raci", {}),
            "skills": r.get("skills", []),
            "used_by": {"owner": owner, "performer_processes": perf_procs,
                        "performer_tasks": perf_tasks, "escalation": esc, "objectives": obj},
            "in_use": count > 0, "use_count": count,
        })
    return out


def landscape(g: cc.Graph | None = None) -> dict:
    """The org's process house: every active process grouped by APQC domain, with
    per-process stats, plus catalogs (roles / KPIs / risks) that thread across
    processes. Phase D navigation — read-only, from the one graph."""
    g = g or cc.Graph()
    procs = sorted((p for p in g.all("Process") if p["status"] == "active"), key=lambda p: p["id"])
    role_use: dict[str, set] = {}
    kpi_use: dict[str, set] = {}
    domains: dict[str, dict] = {}
    for p in procs:
        dom = p["id"][:2]
        tasks = [t for t in g.all("Task") if t["process_ref"] == p["id"] and t["status"] == "active"]
        agent_steps = sum(1 for t in tasks
                          if any(str(w).startswith("agent.") for w in t.get("performed_by", [])))
        gr = g.get("GuardrailPolicy", p.get("guardrail_ref"))
        reviewed = bool(gr and gr.get("review", {}).get("reviewed_by"))
        for t in tasks:
            for w in t.get("performed_by", []):
                if str(w).startswith("role."):
                    role_use.setdefault(w, set()).add(p["id"])
        for k in p.get("kpi_refs", []):
            kpi_use.setdefault(k, set()).add(p["id"])
        e = domains.setdefault(dom, {"code": dom, "name": DOMAIN_NAMES.get(dom, dom), "processes": []})
        e["processes"].append({
            "id": p["id"], "name": p["name"], "owner": p["owner_role"],
            "steps": len(tasks), "agent_steps": agent_steps, "reviewed": reviewed,
            "risks": len(p.get("risk_refs", [])), "kpis": len(p.get("kpi_refs", [])),
        })

    def _name(etype, eid):
        e = g.get(etype, eid)
        return e["name"] if e and e.get("name") else eid

    roles = sorted(({"id": rid, "name": _name("HumanRole", rid), "count": len(ps),
                     "processes": sorted(ps)} for rid, ps in role_use.items()),
                   key=lambda x: (-x["count"], x["id"]))
    kpis = sorted(({"id": kid, "name": _name("KPI", kid), "count": len(ps),
                    "processes": sorted(ps)} for kid, ps in kpi_use.items()),
                  key=lambda x: (-x["count"], x["id"]))
    risks = sorted(({"id": rc["id"], "risk": rc.get("risk", ""), "process": rc.get("process_ref")}
                    for rc in g.all("RiskControl") if rc.get("status") == "active"),
                   key=lambda x: x["id"])
    return {
        "processes_total": len(procs),
        "domains": [domains[d] for d in sorted(domains)],
        "catalogs": {"roles": roles, "kpis": kpis, "risks": risks},
    }


if __name__ == "__main__":
    import json
    print(json.dumps(all_maps(), indent=2)[:1400])
