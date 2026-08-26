"""
Governance write-path tests (Phase 2). No test framework — plain asserts, so it
runs with a bare interpreter. Cleans up the edit log it writes.

    python3 test_store.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)

import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    # start from a clean edit log
    if os.path.exists(cc.EDITS_LOG):
        os.remove(cc.EDITS_LOG)
    s = gov.GovernanceStore()

    before = s.guardrail("gr.CO.3.2.7")
    check("baseline gr.CO.3.2.7 is v3", before["version"] == 3)

    # 1. a valid owner edit bumps the version and records the review trail
    new = s.edit_guardrail(
        "gr.CO.3.2.7",
        {"escalate_if": "risk_score > 0.85"},
        actor="role.ops.support_lead",
        reason="Tighten escalation after Q3 volume spike",
        reviewer="role.ops.support_lead",
    )
    check("edit bumps version 3 -> 4", new["version"] == 4)
    check("edit records reviewer (ISO 9001 §7.5)", new["review"]["reviewed_by"] == "role.ops.support_lead")
    check("edit records reason", "Q3 volume spike" in new["review"]["note"])
    check("edit changed escalate_if", new["escalate_if"] == "risk_score > 0.85")

    # 2. the change is folded live — a fresh Graph (what MCP reads) sees v4
    g = cc.Graph()
    live = g.get("GuardrailPolicy", "gr.CO.3.2.7")
    check("MCP-side Graph sees v4 (one source of truth)", live["version"] == 4)
    check("MCP-side escalate_if updated", live["escalate_if"] == "risk_score > 0.85")

    # 3. the guardrail check now behaves per the new policy (0.9 still escalates > 0.85)
    v = cc.check_guardrail(g, "CO.3.2.7.t3", "verify_document", {"risk_score": 0.9})
    check("agent decision reflects edited policy", v["gr"] == "gr.CO.3.2.7.v4")

    # 4. history shows both versions, newest first
    hist = s.history("gr.CO.3.2.7")
    check("history has 2 versions", len(hist) == 2 and hist[0]["version"] == 4)

    # 5. an invalid edit is REFUSED (never shipped) — bad audit_requirement enum
    try:
        s.edit_guardrail("gr.CO.3.2.7", {"audit_requirement": "whatever"},
                         actor="role.ops.support_lead", reason="x", reviewer="role.ops.support_lead")
        check("invalid enum rejected", False)
    except gov.EditError:
        check("invalid enum rejected", True)

    # 6. a malformed escalate_if is REFUSED by the governance-time lint
    try:
        s.edit_guardrail("gr.CO.3.2.7", {"escalate_if": "risk_score >>> 0.5"},
                         actor="role.ops.support_lead", reason="x", reviewer="role.ops.support_lead")
        check("malformed escalate_if rejected", False)
    except gov.EditError:
        check("malformed escalate_if rejected", True)

    # 7. a missing reason is REFUSED (§7.5 trail)
    try:
        s.edit_guardrail("gr.CO.3.2.7", {"escalate_if": "risk_score > 0.7"},
                         actor="role.ops.support_lead", reason="  ", reviewer="role.ops.support_lead")
        check("empty reason rejected", False)
    except gov.EditError:
        check("empty reason rejected", True)

    # 8. rejected edits did not bump the version (still v4)
    check("rejected edits left version at v4", s.guardrail("gr.CO.3.2.7")["version"] == 4)

    # 9. audit trail includes the one committed change-control event
    aud = s.audit()
    cc_events = [a for a in aud if a["kind"] == "change_control"]
    check("audit shows exactly one committed change", len(cc_events) == 1)

    # cleanup
    os.remove(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
