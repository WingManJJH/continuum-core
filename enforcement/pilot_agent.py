"""
Pilot agent wired to the Enforcement Point — Phase 3 (§09: "wired to one pilot
agent framework").

A deliberately small, framework-agnostic agent loop: it fetches its task context
over the same package the MCP server serves, decides what it wants to do, and
routes EVERY action through the Enforcement Point. It has no direct handle on the
underlying tools — `ep.act(...)` is its only way to affect the world. A real
MCP-native agent (e.g. a Claude agent) substitutes for this loop unchanged; the
contract is the same three calls.

Run the demo:
    python3 pilot_agent.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
from enforce import EnforcementPoint  # noqa: E402

TASK = "CO.3.2.7.t3"
AGENT = "agent.kyc_verifier"


# --- the underlying "tools" the EP guards. The agent never calls these directly.
def _verify_document(facts):
    return {"verified": True, "risk_score": facts.get("risk_score")}


def _request_resubmit(facts):
    return {"resubmit_requested": True}


def build_ep() -> EnforcementPoint:
    ep = EnforcementPoint()
    ep.register("verify_document", _verify_document)
    ep.register("request_resubmit", _request_resubmit)
    return ep


def handle_case(ep: EnforcementPoint, case: dict) -> dict:
    """One agent turn over one customer case. The agent reads context, then acts
    ONLY through the Enforcement Point."""
    # (an agent would parse this package; we just confirm it fetched it)
    _ctx = cc.get_task_context(TASK, ep.g)
    facts = {"risk_score": case["risk_score"], "fields": case.get("fields", ["customer.kyc_doc"])}
    return ep.act(TASK, case["action"], AGENT, facts)


def main():
    # fresh audit + escalation state for a clean demo
    for p in (cc.EVENTS_LOG, os.path.join(os.path.dirname(cc.DATA), "escalations.jsonl")):
        if os.path.exists(p):
            os.remove(p)

    ep = build_ep()
    cases = [
        {"label": "low-risk verify", "action": "verify_document", "risk_score": 0.2},
        {"label": "high-risk verify (should escalate)", "action": "verify_document", "risk_score": 0.9},
        {"label": "forbidden: approve credit limit", "action": "approve_credit_limit", "risk_score": 0.1},
        {"label": "not-on-allow-list: delete customer", "action": "delete_customer", "risk_score": 0.1},
        {"label": "out-of-scope field touch", "action": "verify_document", "risk_score": 0.1,
         "fields": ["customer.credit_history"]},
    ]

    print("=" * 72)
    print(f"PILOT AGENT {AGENT} on {TASK} — every action via the Enforcement Point")
    print("=" * 72)
    for c in cases:
        r = handle_case(ep, c)
        tool_ran = "TOOL RAN" if r["status"] == "executed" else "tool NOT run"
        print(f"\n• {c['label']}")
        print(f"    action={c['action']}  ->  {r['status'].upper()}"
              + (f" ({r.get('reason')})" if r.get("reason") else "")
              + (f" to {r.get('to')}" if r.get("to") else ""))
        print(f"    {tool_ran}  · cited {r['gr']}")

    # rate-limit demo: hammer allowed action past the policy's window
    print("\n" + "-" * 72)
    gr, _ = ep.g.effective_guardrail(TASK)
    rl = gr["rate_limit"]
    print(f"RATE LIMIT demo — policy allows {rl['max_actions']}/{rl['per_seconds']}s; firing {rl['max_actions'] + 2}")
    outcomes = [handle_case(ep, {"action": "verify_document", "risk_score": 0.1})["status"]
                for _ in range(rl["max_actions"] + 2)]
    executed = outcomes.count("executed")
    denied = outcomes.count("denied")
    print(f"    executed={executed}  denied(rate_limited)={denied}")

    # escalation queue
    q = ep.escalation_queue()
    print("\n" + "-" * 72)
    print(f"ESCALATION QUEUE: {len(q)} item(s) awaiting a human")
    for e in q:
        print(f"    {e['task']} · {e['action']} · agent {e['agent']} → {e['assigned_to']} ({e['reason']})")

    print("\n" + "=" * 72)
    print("INVARIANT: the tool ran ONLY on allow — escalate/deny/rate never touched it.")
    print(f"audit trail: {os.path.relpath(cc.EVENTS_LOG, HERE)}")

    # cleanup demo artifacts
    for p in (cc.EVENTS_LOG, os.path.join(os.path.dirname(cc.DATA), "escalations.jsonl")):
        if os.path.exists(p):
            os.remove(p)


if __name__ == "__main__":
    main()
