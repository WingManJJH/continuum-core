"""Approval-gate tests (Phase 3). Plain asserts.

The governance store writes to / folds the real change-control log (the log_path
default is import-bound, so it can't be redirected). So — like test_store — this
runs against the real logs but resets them before AND after, leaving the seed
baseline untouched for the rest of the suite.

    python3 governance/test_approvals.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import approvals as ap  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def a_guardrail_id(store):
    """A guardrail id that exists in the seed, for edit_guardrail proposals."""
    g = store.graph()
    grs = g.all("GuardrailPolicy")
    return grs[0]["id"]


def _reset(paths):
    for p in paths:
        if os.path.exists(p):
            cc.reset_log(p)


def main():
    store = gov.GovernanceStore()
    q = ap.ApprovalQueue(store)
    logs = (cc.EDITS_LOG, cc.EVENTS_LOG, q.log_path)
    _reset(logs)  # clean slate on the real logs
    try:
        gr_id = a_guardrail_id(store)
        base_ver = store.guardrail(gr_id)["version"]

        # --- propose does not touch the model -----------------------------
        cr = q.propose(
            "edit_guardrail",
            {"gr_id": gr_id, "changes": {"escalation_path": "role.qms.iso_advisor"}},
            proposed_by="role.ops.support_lead", reason="tighten escalation",
            title="Escalation path change",
        )
        check("propose returns a pending request", cr["status"] == "pending")
        check("propose did not change the model",
              store.guardrail(gr_id)["version"] == base_ver)
        check("pending_count is 1", q.pending_count() == 1)
        check("proposal appears in pending list",
              q.list(status="pending")[0]["id"] == cr["id"])

        # --- approve applies through the real audited path ----------------
        done = q.approve(cr["id"], reviewer="role.qms.iso_advisor",
                         decision_reason="looks good")
        check("approve marks it approved", done["status"] == "approved")
        check("approve bumped the guardrail version",
              store.guardrail(gr_id)["version"] == base_ver + 1)
        check("approver recorded on the guardrail review block",
              store.guardrail(gr_id)["review"]["reviewed_by"] == "role.qms.iso_advisor")
        check("approve records the applied result",
              done["decision"]["applied"].get("version") == base_ver + 1)
        check("not flagged self-approved (different reviewer)",
              done["decision"]["self_approved"] is False)
        check("pending_count back to 0 after approve", q.pending_count() == 0)

        # --- an approved request can't be approved/rejected again ---------
        try:
            q.approve(cr["id"], "role.qms.iso_advisor")
            check("re-approve refused", False)
        except ap.ApprovalError:
            check("re-approve refused", True)

        # --- reject leaves the model unchanged ----------------------------
        v = store.guardrail(gr_id)["version"]
        cr2 = q.propose("edit_guardrail",
                        {"gr_id": gr_id, "changes": {"escalation_path": "role.ops.support_lead"}},
                        proposed_by="role.ops.support_lead", reason="revert idea")
        rj = q.reject(cr2["id"], reviewer="role.qms.iso_advisor",
                      decision_reason="not needed")
        check("reject marks it rejected", rj["status"] == "rejected")
        check("reject did NOT change the model", store.guardrail(gr_id)["version"] == v)
        try:
            q.reject(cr2["id"], "role.qms.iso_advisor", "again")
            check("reject requires pending", False)
        except ap.ApprovalError:
            check("reject requires pending", True)

        # --- self-approval is allowed but flagged -------------------------
        cr3 = q.propose("edit_guardrail",
                        {"gr_id": gr_id, "changes": {"escalation_path": "role.qms.iso_advisor"}},
                        proposed_by="role.ops.support_lead", reason="self path")
        d3 = q.approve(cr3["id"], reviewer="role.ops.support_lead")
        check("self-approval allowed", d3["status"] == "approved")
        check("self-approval flagged", d3["decision"]["self_approved"] is True)

        # --- withdraw (only the proposer) ---------------------------------
        cr4 = q.propose("edit_guardrail",
                        {"gr_id": gr_id, "changes": {"audit_requirement": "full_capture"}},
                        proposed_by="role.ops.support_lead", reason="maybe later")
        try:
            q.withdraw(cr4["id"], actor="role.qms.iso_advisor")
            check("non-proposer cannot withdraw", False)
        except ap.ApprovalError:
            check("non-proposer cannot withdraw", True)
        wd = q.withdraw(cr4["id"], actor="role.ops.support_lead", decision_reason="dropped")
        check("proposer can withdraw", wd["status"] == "withdrawn")

        # --- validation: unknown op, bad args, bad proposer ---------------
        for bad in [
            lambda: q.propose("delete_everything", {}, "role.ops.support_lead", "x"),
            lambda: q.propose("edit_guardrail", {"nope": 1}, "role.ops.support_lead", "x"),
            lambda: q.propose("edit_guardrail", {"gr_id": gr_id, "changes": {}}, "support_lead", "x"),
            lambda: q.propose("edit_guardrail", {"gr_id": gr_id, "changes": {}}, "role.ops.support_lead", ""),
        ]:
            try:
                bad()
                check("invalid propose refused", False)
            except ap.ApprovalError:
                check("invalid propose refused", True)

        # --- a stale proposal surfaces the store's rejection, stays pending
        cr5 = q.propose("edit_guardrail",
                        {"gr_id": "gr.does_not_exist", "changes": {"escalation_path": "role.x"}},
                        proposed_by="role.ops.support_lead", reason="stale target")
        try:
            q.approve(cr5["id"], reviewer="role.qms.iso_advisor")
            check("approving an unapplicable request errors", False)
        except ap.ApprovalError:
            check("approving an unapplicable request errors", True)
        check("failed approval leaves the request pending",
              q.get(cr5["id"])["status"] == "pending")

        # --- the proposals log is hash-chained (tamper-evident) -----------
        chain = cc.verify_log(q.log_path)
        check("proposals log chain intact", chain["ok"] is True)

        # --- a non-guardrail op flows through the same gate ---------------
        proc = store.graph().all("Process")[0]
        task = [t for t in store.graph().all("Task")
                if t["process_ref"] == proc["id"] and t["status"] == "active"][0]
        crt = q.propose("edit_task",
                        {"task_id": task["id"], "changes": {"name": task["name"] + " (rev)"}},
                        proposed_by="role.ops.support_lead", reason="rename step")
        q.approve(crt["id"], reviewer="role.qms.iso_advisor")
        renamed = store.graph().get("Task", task["id"])
        check("gated task edit applied", renamed["name"].endswith("(rev)"))
    finally:
        _reset(logs)  # leave the seed baseline clean for the rest of the suite

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
