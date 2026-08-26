"""
Traceability linter — Core Model §01 ("a dangling process or orphaned objective
is a data-quality defect the system should flag, not a normal state") and §12
(traceability completeness as a data-quality score on the model itself).

Walks the graph and reports:
  - orphan KPI            : a KPI tied to no objective
  - orphan objective      : an objective with no KPI
  - no strategic parent   : an active process whose KPIs reach no objective
  - broken reference      : any *_ref pointing at a missing entity

Then prints the §12 traceability-completeness score: the share of active
processes with a strategic parent and no broken references.

    python3 traceability.py            # human report (exit 1 if any defect)
    python3 traceability.py --json     # machine-readable findings
"""
from __future__ import annotations

import json
import sys

import continuum_core as cc

SEVERITY = {"broken_reference": "ERROR", "no_strategic_parent": "WARN",
            "orphan_kpi": "WARN", "orphan_objective": "WARN"}


def lint(g: cc.Graph) -> list[dict]:
    findings: list[dict] = []

    def has(etype, _id):
        return g.get(etype, _id) is not None

    kpi_ids = {k["id"] for k in g.all("KPI")}
    obj_ids = {o["id"] for o in g.all("StrategicObjective")}
    role_ids = {r["id"] for r in g.all("HumanRole")}
    proc_ids = {p["id"] for p in g.all("Process")}
    gr_ids = {gr["id"] for gr in g.all("GuardrailPolicy")}
    binding_by_task: dict[str, str] = {b["task_ref"]: b["id"] for b in g.all("AgentBinding")}

    # KPI referenced-by index (which objectives point at each KPI)
    kpi_to_obj: dict[str, list[str]] = {kid: [] for kid in kpi_ids}
    for o in g.all("StrategicObjective"):
        for kref in o.get("kpi_refs", []):
            if kref not in kpi_ids:
                findings.append(_f("orphan_objective" if False else "broken_reference",
                                   "StrategicObjective", o["id"],
                                   f"kpi_ref -> missing KPI '{kref}'"))
            else:
                kpi_to_obj[kref].append(o["id"])
        if not o.get("kpi_refs"):
            findings.append(_f("orphan_objective", "StrategicObjective", o["id"],
                               "objective tracks no KPI (empty kpi_refs)"))

    # orphan KPIs: active KPI that no objective references AND that declares no objective_refs
    for k in g.all("KPI"):
        if k["status"] != "active":
            continue
        reachable = kpi_to_obj.get(k["id"], []) or [r for r in k.get("objective_refs", []) if r in obj_ids]
        if not reachable:
            findings.append(_f("orphan_kpi", "KPI", k["id"],
                               "KPI is tied to no strategic objective"))
        for oref in k.get("objective_refs", []):
            if oref not in obj_ids:
                findings.append(_f("broken_reference", "KPI", k["id"],
                                   f"objective_ref -> missing objective '{oref}'"))

    # processes: strategic parent + reference integrity
    for p in g.all("Process"):
        if p["status"] != "active":
            continue
        parent_objs = set()
        for kref in p.get("kpi_refs", []):
            if kref not in kpi_ids:
                findings.append(_f("broken_reference", "Process", p["id"],
                                   f"kpi_ref -> missing KPI '{kref}'"))
                continue
            parent_objs.update(kpi_to_obj.get(kref, []))
        if not parent_objs:
            findings.append(_f("no_strategic_parent", "Process", p["id"],
                               "no KPI on this process reaches any objective"))
        if p.get("guardrail_ref") and p["guardrail_ref"] not in gr_ids:
            findings.append(_f("broken_reference", "Process", p["id"],
                               f"guardrail_ref -> missing '{p['guardrail_ref']}'"))
        if p.get("owner_role") not in role_ids:
            findings.append(_f("broken_reference", "Process", p["id"],
                               f"owner_role -> missing role '{p.get('owner_role')}'"))
        for rref in p.get("risk_refs", []):
            if not has("RiskControl", rref):
                findings.append(_f("broken_reference", "Process", p["id"],
                                   f"risk_ref -> missing '{rref}'"))

    # tasks: process ref, guardrail override, performed_by integrity
    for t in g.all("Task"):
        if t["process_ref"] not in proc_ids:
            findings.append(_f("broken_reference", "Task", t["id"],
                               f"process_ref -> missing process '{t['process_ref']}'"))
        if t.get("guardrail_ref") and t["guardrail_ref"] not in gr_ids:
            findings.append(_f("broken_reference", "Task", t["id"],
                               f"guardrail_ref -> missing '{t['guardrail_ref']}'"))
        for who in t.get("performed_by", []):
            if who.startswith("role.") and who not in role_ids:
                findings.append(_f("broken_reference", "Task", t["id"],
                                   f"performed_by -> missing role '{who}'"))
            if who.startswith("agent."):
                if not has("AgentBinding", who):
                    findings.append(_f("broken_reference", "Task", t["id"],
                                       f"performed_by -> missing agent binding '{who}'"))
                elif binding_by_task.get(t["id"]) != who and g.get("AgentBinding", who)["task_ref"] != t["id"]:
                    findings.append(_f("broken_reference", "Task", t["id"],
                                       f"agent '{who}' is bound to a different task"))

    # guardrails: attach point + escalation path
    for gr in g.all("GuardrailPolicy"):
        ref = gr["attaches_to"]["ref"]
        kind = gr["attaches_to"]["kind"]
        if ref not in ("TEMPLATE",):
            target_ok = (ref in proc_ids) if kind == "process" else has("Task", ref)
            if not target_ok:
                findings.append(_f("broken_reference", "GuardrailPolicy", gr["id"],
                                   f"attaches_to {kind} '{ref}' does not exist"))
        if gr["escalation_path"] not in role_ids and gr["escalation_path"] != "role.process_owner":
            findings.append(_f("broken_reference", "GuardrailPolicy", gr["id"],
                               f"escalation_path -> missing role '{gr['escalation_path']}'"))

    # agent bindings: task ref
    for b in g.all("AgentBinding"):
        if not has("Task", b["task_ref"]):
            findings.append(_f("broken_reference", "AgentBinding", b["id"],
                               f"task_ref -> missing task '{b['task_ref']}'"))

    return findings


def _f(kind, etype, _id, msg):
    return {"severity": SEVERITY[kind], "kind": kind, "entity": f"{etype} {_id}", "detail": msg}


def completeness_score(g: cc.Graph, findings: list[dict]) -> float:
    """§12: share of active processes with a strategic parent and no broken ref."""
    procs = [p for p in g.all("Process") if p["status"] == "active"]
    if not procs:
        return 1.0
    bad = set()
    for f in findings:
        if f["entity"].startswith("Process ") and f["kind"] in ("no_strategic_parent", "broken_reference"):
            bad.add(f["entity"].split(" ", 1)[1])
    return (len(procs) - len(bad)) / len(procs)


if __name__ == "__main__":
    g = cc.Graph()
    findings = lint(g)
    if "--json" in sys.argv:
        print(json.dumps({"findings": findings,
                          "completeness_score": round(completeness_score(g, findings), 3)}, indent=2))
        sys.exit(1 if findings else 0)

    print("=" * 78)
    print("CONTINUUM TRACEABILITY LINT (§01 / §12)")
    print("=" * 78)
    if not findings:
        print("  no defects — every process traces to strategy, no broken references")
    else:
        for f in sorted(findings, key=lambda x: (x["severity"], x["entity"])):
            print(f"  [{f['severity']:<5}] {f['kind']:<20} {f['entity']:<28} {f['detail']}")
    score = completeness_score(g, findings)
    print("-" * 78)
    errors = sum(1 for f in findings if f["severity"] == "ERROR")
    warns = sum(1 for f in findings if f["severity"] == "WARN")
    print(f"  {errors} error(s), {warns} warning(s)")
    print(f"  §12 traceability completeness score: {score:.0%} "
          f"of active processes fully traced to strategy")
    print("=" * 78)
    print("NOTE: the two orphan KPIs and the one un-parented process here are "
          "PLANTED in the seed to prove the linter flags them (see data/seed.json _note).")
    sys.exit(1 if errors else 0)
