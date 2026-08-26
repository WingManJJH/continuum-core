"""
Strategy-to-execution rollup — Phase 4 (Core Model §05, §12, §09 Phase 4).

The standing report, not a special request (§05): because the spine is one graph,
tracing is a walk, not a research project.

  strategy()   top-down: objective → KPI (live vs target) → process → agent-bound
               task → guardrail version + what the agent actually did last period.
  bottom_up()  agent actions rolled up: task → process → KPI → objective.
  coverage()   §12 guardrail coverage — every agent-bound task, whether it runs
               under a reviewed, versioned guardrail (fail-closed: an agent-bound
               task with no effective guardrail is a defect, not a silent allow).
  metrics()    the §12 success metrics, with the ones that need human disposition
               data marked needs_data rather than fabricated.

Agent activity comes from the action log the Enforcement Point writes
(data/events.log.jsonl); pass an explicit list for deterministic reports/tests.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import traceability as trace  # noqa: E402


def _kpi_status(k: dict) -> str:
    lv = k.get("live_value")
    if lv is None:
        return "no_data"
    if k["direction"] == "lower_is_better":
        return "on_target" if lv <= k["target"] else "off_target"
    return "on_target" if lv >= k["target"] else "off_target"


def load_agent_events(path: str | None = None) -> list[dict]:
    path = path or cc.EVENTS_LOG
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


class Rollup:
    def __init__(self, graph: cc.Graph | None = None):
        self.g = graph or cc.Graph()
        self._kpi_to_procs = {}
        for p in self.g.all("Process"):
            for kref in p.get("kpi_refs", []):
                self._kpi_to_procs.setdefault(kref, []).append(p["id"])

    # --- helpers -----------------------------------------------------------
    def _agent_tasks(self) -> list[dict]:
        return [t for t in self.g.all("Task")
                if any(w.startswith("agent.") for w in t.get("performed_by", []))]

    @staticmethod
    def _activity(events: list[dict], task_id: str) -> dict:
        rows = [e for e in events if e.get("entity_id") == task_id
                and e.get("actor", {}).get("kind") == "agent"]
        counts = {"success": 0, "escalated": 0, "denied": 0, "rate_limited": 0}
        last_gr = None
        for e in rows:
            oc = e.get("payload", {}).get("outcome")
            if oc in counts:
                counts[oc] += 1
            last_gr = e.get("payload", {}).get("guardrail_version", last_gr)
        return {"counts": counts, "total": len(rows), "last_guardrail": last_gr}

    def _effective(self, task_id: str):
        return self.g.effective_guardrail(task_id)

    # --- top-down ----------------------------------------------------------
    def strategy(self, events: list[dict] | None = None) -> dict:
        events = events if events is not None else load_agent_events()
        objectives = []
        for obj in self.g.all("StrategicObjective"):
            kpis = []
            for kref in obj.get("kpi_refs", []):
                k = self.g.get("KPI", kref)
                if not k:
                    kpis.append({"id": kref, "status": "MISSING"})
                    continue
                procs = []
                for pid in self._kpi_to_procs.get(kref, []):
                    p = self.g.get("Process", pid)
                    atasks = []
                    for t in self._agent_tasks():
                        if t["process_ref"] != pid:
                            continue
                        gr, pinned = self._effective(t["id"])
                        atasks.append({
                            "task": t["id"], "name": t["name"],
                            "agents": [w for w in t["performed_by"] if w.startswith("agent.")],
                            "guardrail": pinned,
                            "activity": self._activity(events, t["id"]),
                        })
                    procs.append({"process": pid, "name": p["name"],
                                  "owner": p["owner_role"], "agent_tasks": atasks})
                kpis.append({"id": k["id"], "name": k["name"], "unit": k["unit"],
                             "live_value": k.get("live_value"), "target": k["target"],
                             "status": _kpi_status(k), "processes": procs})
            objectives.append({"id": obj["id"], "name": obj["name"],
                               "owner": obj["owner_role"], "horizon": obj["horizon"],
                               "kpis": kpis})
        return {"objectives": objectives}

    # --- bottom-up ---------------------------------------------------------
    def bottom_up(self, events: list[dict] | None = None) -> list[dict]:
        events = events if events is not None else load_agent_events()
        out = []
        for t in self._agent_tasks():
            act = self._activity(events, t["id"])
            if act["total"] == 0:
                continue
            p = self.g.get("Process", t["process_ref"])
            kpi_ids = p.get("kpi_refs", []) if p else []
            obj_ids = sorted({o for kid in kpi_ids
                              for o in (self.g.get("KPI", kid) or {}).get("objective_refs", [])})
            out.append({"task": t["id"], "process": t["process_ref"],
                        "kpis": kpi_ids, "objectives": obj_ids,
                        "activity": act["counts"], "total": act["total"]})
        return out

    # --- §12 guardrail coverage (fail-closed) ------------------------------
    def coverage(self) -> dict:
        per = []
        for t in self._agent_tasks():
            gr, pinned = self._effective(t["id"])
            reviewed = bool(gr and gr.get("review", {}).get("reviewed_by"))
            versioned = bool(gr and gr.get("version"))
            state = ("missing" if gr is None
                     else "reviewed" if (reviewed and versioned) else "default")
            per.append({"task": t["id"], "guardrail": pinned, "state": state})
        total = len(per)
        covered = sum(1 for x in per if x["state"] == "reviewed")
        missing = [x["task"] for x in per if x["state"] == "missing"]
        return {"total_agent_tasks": total, "reviewed": covered,
                "pct": round(covered / total * 100) if total else 100,
                "uncovered": [x for x in per if x["state"] != "reviewed"],
                "fail_closed_defects": missing, "per_task": per}

    # --- §12 success metrics ----------------------------------------------
    def metrics(self, events: list[dict] | None = None,
                escalation_dispositions: list[dict] | None = None) -> dict:
        events = events if events is not None else load_agent_events()
        cov = self.coverage()
        findings = trace.lint(self.g)
        tc = trace.completeness_score(self.g, findings)

        act = {"success": 0, "escalated": 0, "denied": 0, "rate_limited": 0}
        for e in events:
            oc = e.get("payload", {}).get("outcome")
            if oc in act:
                act[oc] += 1

        # escalation precision needs human dispositions (did the human actually
        # need to act?). Report needs_data unless dispositions are supplied.
        if escalation_dispositions:
            needed = sum(1 for d in escalation_dispositions if d.get("action_needed"))
            esc_precision = {"value": round(needed / len(escalation_dispositions), 2),
                             "n": len(escalation_dispositions)}
        else:
            esc_precision = {"value": None, "needs_data": "human escalation dispositions"}

        return {
            "guardrail_coverage": {"value": cov["pct"], "unit": "percent",
                                   "detail": f"{cov['reviewed']}/{cov['total_agent_tasks']} agent-bound tasks under a reviewed, versioned guardrail",
                                   "fail_closed_defects": cov["fail_closed_defects"]},
            "traceability_completeness": {"value": round(tc * 100), "unit": "percent",
                                          "detail": f"{sum(1 for f in findings if f['kind']=='no_strategic_parent')} process(es) with no strategic parent"},
            "agent_activity": act,
            "escalation_precision": esc_precision,
            "drift_to_update_latency": {"value": None,
                                        "needs_data": "conformance finding timestamps + human resolution timestamps (Phase 4 signal, connector-auth-gated)"},
        }


if __name__ == "__main__":
    r = Rollup()
    events = load_agent_events()
    print("STRATEGY-TO-EXECUTION ROLLUP (§05) — standing report")
    print("=" * 68)
    for o in r.strategy(events)["objectives"]:
        print(f"\n* {o['id']}  (owner {o['owner']}, {o['horizon']})")
        for k in o["kpis"]:
            print(f"   KPI {k['id']}: {k.get('live_value')}/{k.get('target')} {k.get('unit', '')} [{k['status']}]")
            for p in k.get("processes", []):
                for at in p["agent_tasks"]:
                    c = at["activity"]["counts"]
                    print(f"      task {at['task']} via {','.join(at['agents'])} [{at['guardrail']}] "
                          f"acts: {c['success']} ok / {c['escalated']} esc / {c['denied']} deny")
    m = r.metrics(events)
    print("\n" + "=" * 68)
    print("§12 SUCCESS METRICS")
    print(f"   guardrail coverage:        {m['guardrail_coverage']['value']}%  "
          f"({m['guardrail_coverage']['detail']})")
    print(f"   traceability completeness: {m['traceability_completeness']['value']}%")
    print(f"   agent activity:            {m['agent_activity']}")
    ep = m['escalation_precision']
    print(f"   escalation precision:      {ep['value'] if ep.get('value') is not None else 'needs data: ' + ep['needs_data']}")
    print(f"   drift-to-update latency:   needs data: {m['drift_to_update_latency']['needs_data']}")
