"""Approval-policy tests (Phase 3). Plain asserts, hermetic — the policy log and
the chain-head anchor are temp files, so no shared state is touched.

    python3 governance/test_approval_policy.py
"""
from __future__ import annotations

import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import approval_policy as pol  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def run(tmp):
    p = pol.ApprovalPolicy(log_path=os.path.join(tmp, "approval-policy.log.jsonl"))

    # defaults
    check("defaults: guardrails optional", p.mode_for_entity("GuardrailPolicy") == "optional")
    check("defaults: x-matrix links off", p.mode_for_entity("Correlation") == "off")
    check("op maps to entity mode", p.mode_for_op("edit_task") == "optional")
    check("unknown op is optional (safe default)", p.mode_for_op("nonsense") == "optional")
    check("entities() lists every gated type", len(p.entities()) == len(pol.GATED_ENTITIES))

    # set + fold
    p.set("Task", "required", actor="role.qms.iso_advisor", reason="tighten step control")
    check("set persists via fold", p.mode_for_entity("Task") == "required")
    check("requires_gate reflects required", p.requires_gate("Task") is True)
    check("requires_gate false for optional", p.requires_gate("GuardrailPolicy") is False)

    # latest write wins
    p.set("Task", "off", actor="role.qms.iso_advisor", reason="relax again")
    check("latest policy write wins", p.mode_for_entity("Task") == "off")

    # audit: the policy log is hash-chained
    chain = cc.verify_log(p.log_path)
    check("policy log chain intact", chain["ok"] is True and chain["count"] == 2)

    # validation
    for bad in [
        lambda: p.set("Nope", "required", "role.x", "r"),
        lambda: p.set("Task", "sometimes", "role.x", "r"),
        lambda: p.set("Task", "required", "not_a_role", "r"),
        lambda: p.set("Task", "required", "role.x", ""),
    ]:
        try:
            bad()
            check("invalid policy set refused", False)
        except pol.PolicyError:
            check("invalid policy set refused", True)


def main():
    with tempfile.TemporaryDirectory() as tmp:
        heads_save = cc.HEADS_FILE
        cc.HEADS_FILE = os.path.join(tmp, "audit_heads.json")  # isolate the chain head
        try:
            run(tmp)
        finally:
            cc.HEADS_FILE = heads_save
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
