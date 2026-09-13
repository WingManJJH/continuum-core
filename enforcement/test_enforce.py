"""Enforcement Point tests (Phase 3). Plain asserts; cleans its logs.

    python3 test_enforce.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
from enforce import EnforcementPoint, ESCALATIONS  # noqa: E402

TASK, AGENT = "CO.3.2.7.t3", "agent.kyc_verifier"
PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def clean():
    cc.reset_log(cc.EVENTS_LOG)            # log + heads anchor together
    if os.path.exists(ESCALATIONS):
        os.remove(ESCALATIONS)


def main():
    clean()
    calls = {"n": 0}
    ep = EnforcementPoint()
    ep.register("verify_document", lambda f: (calls.__setitem__("n", calls["n"] + 1), {"verified": True})[1])

    # allow executes the tool
    r = ep.act(TASK, "verify_document", AGENT, {"risk_score": 0.2})
    check("allow → executed", r["status"] == "executed" and r["result"] == {"verified": True})
    check("allow ran the tool exactly once", calls["n"] == 1)

    # escalate does NOT execute; queues for a human
    r = ep.act(TASK, "verify_document", AGENT, {"risk_score": 0.9})
    check("high risk → escalated", r["status"] == "escalated" and r["to"] == "role.ops.support_lead")
    check("escalate did NOT run the tool", calls["n"] == 1)

    # deny variants never execute
    check("forbidden → denied", ep.act(TASK, "approve_credit_limit", AGENT)["reason"] == "action_forbidden")
    check("unknown action → denied", ep.act(TASK, "delete_customer", AGENT)["reason"] == "action_not_allowed")
    check("out-of-scope → denied",
          ep.act(TASK, "verify_document", AGENT, {"fields": ["customer.credit_history"]})["reason"] == "out_of_scope")
    check("no denied action ran the tool", calls["n"] == 1)

    # escalation queue has the one escalated item
    q = ep.escalation_queue()
    check("escalation queue has 1 item for a human", len(q) == 1 and q[0]["assigned_to"] == "role.ops.support_lead")

    # rate limit: exhaust the window on a fresh EP, tool stops running at the cap
    clean()
    calls2 = {"n": 0}
    ep2 = EnforcementPoint()
    ep2.register("verify_document", lambda f: calls2.__setitem__("n", calls2["n"] + 1))
    gr, _ = ep2.g.effective_guardrail(TASK)
    cap = gr["rate_limit"]["max_actions"]
    outs = [ep2.act(TASK, "verify_document", AGENT, {"risk_score": 0.1})["status"] for _ in range(cap + 3)]
    check(f"rate limit: exactly {cap} executed", outs.count("executed") == cap)
    check("rate limit: overflow denied", outs.count("denied") == 3)
    check("rate limit: tool ran only up to the cap", calls2["n"] == cap)

    # audit trail captured every outcome kind
    events = [__import__("json").loads(x) for x in open(cc.EVENTS_LOG)] if os.path.exists(cc.EVENTS_LOG) else []
    outcomes = {e["payload"]["outcome"] for e in events}
    check("audit recorded rate_limited + success", {"success", "rate_limited"} <= outcomes)

    clean()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
