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
import continuum_core as cc  # noqa: E402


def all_maps(g: cc.Graph | None = None) -> list[dict]:
    g = g or cc.Graph()
    out = []
    for p in sorted(g.all("Process"), key=lambda x: x["id"]):
        pgr = g.get("GuardrailPolicy", p.get("guardrail_ref"))
        risks = [{"id": r["id"], "risk": r["risk"]}
                 for r in (g.get("RiskControl", rr) for rr in p.get("risk_refs", [])) if r]
        tasks = []
        for t in sorted((t for t in g.all("Task") if t["process_ref"] == p["id"]),
                        key=lambda t: t["seq"]):
            gr, pinned = g.effective_guardrail(t["id"])
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
            })
        out.append({
            "id": p["id"], "name": p["name"], "owner": p["owner_role"],
            "guardrail": f"{p['guardrail_ref']}.v{pgr['version']}" if pgr else None,
            "kpis": p.get("kpi_refs", []), "risks": risks, "tasks": tasks,
        })
    return out


if __name__ == "__main__":
    import json
    print(json.dumps(all_maps(), indent=2)[:1400])
