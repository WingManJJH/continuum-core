"""
Full-enforcement sweep — Phase 4 (§09: "Full guardrail enforcement across all
agent-bound tasks").

Drives the Enforcement Point across EVERY agent-bound task in the model, not just
the KYC pilot: for each, it runs the guardrail's first allowed action (benign →
execute; trigger facts → escalate where the policy has a condition) and its first
forbidden action (→ deny). This proves the gate is universal and, as a side
effect, populates the agent action log the §05 dashboard reads.

Fail-closed: an agent-bound task with no effective guardrail is a coverage defect,
reported here and by dashboard/rollup.coverage().

    python3 sweep.py            # run the sweep (writes data/events.log.jsonl)
    python3 sweep.py --keep     # keep the log for the dashboard to display
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "dashboard"))
import continuum_core as cc  # noqa: E402
from enforce import EnforcementPoint, ESCALATIONS  # noqa: E402
from rollup import Rollup  # noqa: E402

BENIGN = {"risk_score": 0.0, "amount": 0, "vendor_risk": 0.0, "deal_size": 0,
          "resource_sensitivity": 0.0, "severity": 0, "applicant_score": 1.0,
          "confidence": 1.0, "budget_impact": 0}
TRIGGER = {"risk_score": 0.99, "amount": 10 ** 9, "vendor_risk": 0.99, "deal_size": 10 ** 9,
           "resource_sensitivity": 0.99, "severity": 5, "applicant_score": 0.0,
           "confidence": 0.0, "budget_impact": 10 ** 9}


def _clean():
    cc.reset_log(cc.EVENTS_LOG)            # log + heads anchor together
    if os.path.exists(ESCALATIONS):
        os.remove(ESCALATIONS)


def main():
    keep = "--keep" in sys.argv
    _clean()

    ep = EnforcementPoint()
    g = ep.g
    agent_tasks = [t for t in g.all("Task")
                   if any(w.startswith("agent.") for w in t.get("performed_by", []))]

    print("=" * 74)
    print(f"FULL ENFORCEMENT SWEEP — {len(agent_tasks)} agent-bound tasks, every action via the EP")
    print("=" * 74)
    print(f"{'task':<16}{'agent':<22}{'allow':<9}{'escalate':<10}{'deny'}")
    print("-" * 74)
    for t in sorted(agent_tasks, key=lambda x: x["id"]):
        agent = next(w for w in t["performed_by"] if w.startswith("agent."))
        gr, pinned = g.effective_guardrail(t["id"])
        if gr is None:
            print(f"{t['id']:<16}{agent:<22}FAIL-CLOSED: no guardrail (coverage defect)")
            continue
        allowed = gr["allowed_actions"][0]
        forbidden = gr["forbidden_actions"][0] if gr["forbidden_actions"] else None
        r_exec = ep.act(t["id"], allowed, agent, BENIGN)["status"]
        r_esc = ep.act(t["id"], allowed, agent, TRIGGER)["status"] if gr.get("escalate_if") else "n/a"
        r_deny = ep.act(t["id"], forbidden, agent, BENIGN)["status"] if forbidden else "n/a"
        print(f"{t['id']:<16}{agent:<22}{r_exec:<9}{r_esc:<10}{r_deny}")

    cov = Rollup(g).coverage()
    print("-" * 74)
    print(f"§12 GUARDRAIL COVERAGE: {cov['reviewed']}/{cov['total_agent_tasks']} "
          f"agent-bound tasks under a reviewed, versioned guardrail ({cov['pct']}%)")
    if cov["fail_closed_defects"]:
        print(f"  FAIL-CLOSED DEFECTS (no guardrail): {cov['fail_closed_defects']}")
    not_reviewed = [x["task"] for x in cov["uncovered"]]
    if not_reviewed:
        print(f"  not yet reviewed (running under a default): {not_reviewed}")
    q = ep.escalation_queue()
    print(f"escalations queued for humans: {len(q)}")
    print(f"agent action log: {os.path.relpath(cc.EVENTS_LOG, HERE)}"
          + ("  (kept for the dashboard)" if keep else ""))

    if not keep:
        _clean()


if __name__ == "__main__":
    main()
