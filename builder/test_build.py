"""Build-from-instructions tests (D37). Plain asserts.

Turns a list of instructions into a governed process — deterministically (no key)
and via the LLM seam (hermetically, with an injected transport). Everything lands
through the same audited write path as import.

    python3 test_build.py
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "bpmn"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import mapdata  # noqa: E402
import build  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


INSTRUCTIONS = (
    "Process: Vendor onboarding\n"
    "1. Procurement Lead receives the vendor request\n"
    "2. The system automatically checks the vendor against the sanctions list\n"
    "3. If the vendor is high risk, escalate to the CISO\n"
    "4. Finance Manager approves the vendor\n"
    "5. Buyer creates the purchase order"
)


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()

    # 1. deterministic reader
    pb = build.plan_build(INSTRUCTIONS)
    plan = pb["plan"]
    check("reads the process name", plan["name"] == "Vendor onboarding")
    check("counts steps / gateway / agent", plan["counts"]["steps"] == 5 and plan["counts"]["gateways"] == 1 and plan["counts"]["agent_steps"] == 1)
    check("a decision line becomes a gateway", any(x["kind"] == "decision" for x in plan["preview"]))
    check("an automated step is flagged agent", any(x["agent"] for x in plan["preview"]))
    check("a performer role is deduced", any(x.get("role") for x in plan["preview"]))
    check("assumptions are surfaced, not hidden", len(plan["assumptions"]) >= 3 and any("guardrail" in a for a in plan["assumptions"]))
    check("source is the deterministic reader", plan["source"] == "rules")

    # enhanced reader: bare title line, lowercase / single-word roles, drafted branch
    basic = ("Invoice approval\n"
             "the ap clerk receives the invoice\n"
             "the system checks it against the PO\n"
             "if the amount is over 500, the finance manager approves it\n"
             "finance posts the payment\n"
             "notify the vendor")
    bp = build.plan_build(basic)
    bplan = bp["plan"]
    check("an unlabelled first line is used as the process name", bplan["name"] == "Invoice approval")
    roles_found = {x["role"] for x in bplan["preview"] if x.get("role")}
    check("lowercase + single-word performers are deduced",
          "role.ap_clerk" in roles_found and "role.finance_manager" in roles_found and "role.finance" in roles_found)
    check("an imperative step is NOT read as a role", all(not x.get("role") for x in bplan["preview"] if x["name"].startswith("Notify")))
    check("an automated 'the system …' step gets no bogus role",
          all(not x.get("role") for x in bplan["preview"] if x["agent"]))
    drafted = [f for f in bp["parsed"]["flows"] if f.get("condition")]
    check("a branch condition is drafted from an 'If …' line", any("over 500" in (f["condition"] or "") for f in drafted))
    check("the drafted-branch assumption is surfaced", any("branch condition" in a for a in bplan["assumptions"]))

    # 2. apply -> a governed process through the audited write path
    before = os.path.getsize(cc.EDITS_LOG) if os.path.exists(cc.EDITS_LOG) else 0
    _ = build.plan_build(INSTRUCTIONS)  # planning again writes nothing
    check("planning writes nothing", (os.path.getsize(cc.EDITS_LOG) if os.path.exists(cc.EDITS_LOG) else 0) == before)

    res = build.apply_build(pb["parsed"], code="BI.1.1", store=s)
    check("apply mints the process", res["code"] == "BI.1.1" and res["counts"]["gateways"] == 1)
    g = cc.Graph()
    m = next(x for x in mapdata.all_maps(g) if x["id"] == "BI.1.1")
    check("steps + gateway + flows built", len(m["tasks"]) == 5 and len(m["gateways"]) == 1 and len(m["flows"]) == 7)
    check("a deduced role was created + attached", g.get("HumanRole", "role.procurement_lead") is not None
          and any("role.procurement_lead" in t["roles"] for t in m["tasks"]))
    check("the automated step came in agent-bound", any(t["agents"] for t in m["tasks"]))
    check("audit chain intact after build", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    # 3. LLM reader (hermetic — injected transport, no key/network)
    def transport(system, user):
        return json.dumps({"name": "Refund handling", "steps": [
            {"name": "Receive refund request", "performer": "Support Agent", "automated": False, "decision": False},
            {"name": "Amount over 100?", "performer": None, "automated": False, "decision": True},
            {"name": "Auto-approve small refund", "performer": None, "automated": True, "decision": False},
        ]})
    lp = build.plan_build("refund stuff", use_llm=True, transport=transport)
    check("LLM plan is used when a transport is available", lp["plan"]["source"] == "llm" and lp["plan"]["name"] == "Refund handling")
    check("LLM plan maps decision + automated flags", lp["plan"]["counts"]["gateways"] == 1 and lp["plan"]["counts"]["agent_steps"] == 1)

    def bad_transport(system, user):
        return "not json at all"
    fb = build.plan_build(INSTRUCTIONS, use_llm=True, transport=bad_transport)
    check("an unusable LLM reply falls back to the deterministic reader", fb["plan"]["source"] == "rules")

    # 4. empty input refused
    try:
        build.plan_build("   "); ok = False
    except ValueError:
        ok = True
    check("empty instructions are refused", ok)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
