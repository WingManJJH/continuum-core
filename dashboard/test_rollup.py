"""Rollup / dashboard engine tests (Phase 4). Plain asserts; uses a fixed
in-memory agent-event list so it's deterministic regardless of the live log.

    python3 test_rollup.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
from rollup import Rollup  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def ev(task, action, outcome, gr):
    return {"entity_type": "Task", "entity_id": task,
            "actor": {"kind": "agent", "id": "agent.kyc_verifier"},
            "payload": {"action": action, "outcome": outcome, "guardrail_version": gr}}


def main():
    g = cc.Graph()
    r = Rollup(g)
    events = [
        ev("CO.3.2.7.t3", "verify_document", "success", "gr.CO.3.2.7.v3"),
        ev("CO.3.2.7.t3", "verify_document", "escalated", "gr.CO.3.2.7.v3"),
        ev("CO.3.2.7.t3", "approve_credit_limit", "denied", "gr.CO.3.2.7.v3"),
    ]

    # top-down: KYC objective present, KPI status computed, agent task activity attached
    strat = r.strategy(events)
    obj = next(o for o in strat["objectives"] if o["id"] == "obj.reduce_onboarding_friction")
    ttv = next(k for k in obj["kpis"] if k["id"] == "kpi.time_to_verify")
    check("KPI status computed (time_to_verify off_target: 6.2 > 4)", ttv["status"] == "off_target")
    at = ttv["processes"][0]["agent_tasks"][0]
    check("agent-bound task surfaced under the KPI", at["task"] == "CO.3.2.7.t3")
    check("activity counts rolled onto the task", at["activity"]["counts"]["success"] == 1
          and at["activity"]["counts"]["escalated"] == 1 and at["activity"]["counts"]["denied"] == 1)

    # coverage: 8 agent-bound tasks; only CO's guardrail is reviewed (has a review block)
    cov = r.coverage()
    check("8 agent-bound tasks found", cov["total_agent_tasks"] == 8)
    check("only the signed-off KYC guardrail counts as reviewed", cov["reviewed"] == 1 and cov["pct"] == 12)
    check("no fail-closed defects (every agent task has a guardrail)", cov["fail_closed_defects"] == [])

    # bottom-up: CO.3.2.7.t3 rolls up to its KPIs and objective
    bu = r.bottom_up(events)
    co = next(b for b in bu if b["task"] == "CO.3.2.7.t3")
    check("bottom-up traces task → objective", "obj.reduce_onboarding_friction" in co["objectives"])
    check("bottom-up totals actions", co["total"] == 3)

    # metrics: derivable ones have values; disposition-dependent ones are needs_data (not fabricated)
    m = r.metrics(events)
    check("guardrail coverage metric = 12%", m["guardrail_coverage"]["value"] == 12)
    check("traceability completeness = 88%", m["traceability_completeness"]["value"] == 88)
    check("escalation precision marked needs_data (no dispositions)", m["escalation_precision"]["value"] is None)
    check("drift-to-update latency marked needs_data", m["drift_to_update_latency"]["value"] is None)

    # with dispositions supplied, escalation precision computes
    disp = [{"action_needed": True}, {"action_needed": False}, {"action_needed": True}, {"action_needed": True}]
    m2 = r.metrics(events, escalation_dispositions=disp)
    check("escalation precision computes from dispositions (3/4 = 0.75)", m2["escalation_precision"]["value"] == 0.75)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
