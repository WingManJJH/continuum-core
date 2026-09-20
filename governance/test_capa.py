"""CAPA — corrective/preventive action register tests. Plain asserts, hermetic:
every write goes to a throwaway model dir (a copy of the seed with an empty
register), so the real data/ logs are never touched.

    python3 governance/test_capa.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import capa  # noqa: E402

PASS, FAIL = [], []
TODAY = "2026-09-20"


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def _fresh_model(tmp: str) -> None:
    """A clean model: the real seed's roles/processes/risks, an empty register."""
    base = os.path.join(tmp, "capatest")
    os.makedirs(base, exist_ok=True)
    seed = json.load(open(os.path.join(HERE, "..", "data", "seed.json")))
    seed["CorrectiveAction"] = []
    with open(os.path.join(base, "seed.json"), "w") as f:
        json.dump(seed, f)


def _drive_to_closed(s, cid):
    """Walk a CAR through the full lifecycle, filling the §10.2 gates on the way."""
    if cc.Graph().get("CorrectiveAction", cid)["state"] == "open":
        s.transition(cid, "investigating", ACTOR, "start")
    s.edit_car(cid, {"root_cause": "the step skipped the escalation branch"}, ACTOR, "rca")
    s.transition(cid, "action_planned", ACTOR, "plan")
    s.transition(cid, "implemented", ACTOR, "did it")
    s.transition(cid, "verifying", ACTOR, "checking")
    s.edit_car(cid, {"corrective_action": "tightened the guardrail",
                     "effectiveness_check": "re-ran the scenario, no recurrence in 30 days"}, ACTOR, "verify")
    return s.transition(cid, "closed", ACTOR, "done")


ACTOR = "role.qms.iso_advisor"


def run():
    tmp = tempfile.mkdtemp()
    models_save, active_save = cc.MODELS_DIR, cc.ACTIVE_MODEL
    cc.MODELS_DIR = os.path.join(tmp, "models")
    os.makedirs(cc.MODELS_DIR, exist_ok=True)
    _fresh_model(cc.MODELS_DIR)
    cc.set_active_model("capatest")
    try:
        s = capa.CAPAStore()

        # --- raise -------------------------------------------------------
        c1 = s.raise_car("KYC false approvals", "KPI breach on the KYC verification rate",
                         source="kpi_breach", severity="major", owner_role="role.ops.support_lead",
                         affected_process_refs=["CO.3.2.7"], actor=ACTOR,
                         reason="open a CAR for the KPI breach", date_raised="2026-09-05",
                         date_due="2026-10-05", risk_refs=["rc.kyc_false_verify"])
        check("raise: numbers the CAR car.<year>.001", c1["id"] == "car.2026.001")
        check("raise: opens in state=open", c1["state"] == "open" and c1["status"] == "active")
        check("raise: schema-valid", not list(s._validator.iter_errors(c1)))
        check("raise: folds into the graph", cc.Graph().get("CorrectiveAction", "car.2026.001") is not None)

        c2 = s.raise_car("Duplicate reimbursements", "Audit found double-paid claims",
                         source="internal_audit", severity="minor", owner_role="role.finance.ap_lead",
                         affected_process_refs=["FN.9.3.1"], actor=ACTOR, reason="open second CAR",
                         date_raised="2026-09-01", date_due="2026-09-15", risk_refs=["rc.expense_fraud"])
        check("raise: sequence increments to .002", c2["id"] == "car.2026.002")

        for bad, kw in (("owner", dict(owner_role="role.does.not_exist")),
                        ("process", dict(affected_process_refs=["ZZ.9.9"]))):
            try:
                s.raise_car("x", "y", "other", "minor", actor=ACTOR, reason="r",
                            **{"owner_role": "role.ops.support_lead", "affected_process_refs": ["CO.3.2.7"], **kw})
                check(f"raise: rejects unknown {bad}", False)
            except capa.CAPAError:
                check(f"raise: rejects unknown {bad}", True)
        try:
            s.raise_car("x", "y", "not_a_source", "minor", "role.ops.support_lead", ["CO.3.2.7"], ACTOR, "r")
            check("raise: rejects an invalid source enum", False)
        except capa.CAPAError:
            check("raise: rejects an invalid source enum", True)

        # --- edit --------------------------------------------------------
        e = s.edit_car("car.2026.001", {"severity": "critical"}, ACTOR, "reassess severity")
        check("edit: bumps the version", e["version"] == 2)
        check("edit: change applied", cc.Graph().get("CorrectiveAction", "car.2026.001")["severity"] == "critical")
        try:
            s.edit_car("car.2026.001", {"state": "closed"}, ACTOR, "sneaky")
            check("edit: refuses to change state directly", False)
        except capa.CAPAError:
            check("edit: refuses to change state directly", True)

        # --- lifecycle ---------------------------------------------------
        try:
            s.transition("car.2026.002", "closed", ACTOR, "skip")
            check("transition: forbids an illegal jump (open→closed)", False)
        except capa.CAPAError:
            check("transition: forbids an illegal jump (open→closed)", True)
        s.transition("car.2026.002", "investigating", ACTOR, "look into it")
        try:
            s.transition("car.2026.002", "action_planned", ACTOR, "plan")
            check("transition: needs a root cause before action_planned", False)
        except capa.CAPAError:
            check("transition: needs a root cause before action_planned", True)

        closed = _drive_to_closed(s, "car.2026.002")
        check("transition: drives to closed through the gates", closed["state"] == "closed")
        check("transition: stamps date_closed on closure", closed["date_closed"] == TODAY)

        reopened = s.transition("car.2026.002", "investigating", ACTOR, "recurred")
        check("transition: reopening a closed CAR clears date_closed", reopened["date_closed"] is None)

        # --- register / overdue / flags ---------------------------------
        c3 = s.raise_car("Overdue thing", "something", "incident", "critical",
                         "role.it.security_lead", ["IT.8.4.2"], ACTOR, "open overdue CAR",
                         date_raised="2026-07-01", date_due="2026-08-01")
        reg = {c["id"]: c for c in s.register(today=TODAY)}
        check("register: past-due open CAR is flagged overdue", reg[c3["id"]]["overdue"] is True)
        check("register: computes age in days", reg[c3["id"]]["age_days"] == 81)
        check("register: enriches affected processes with names+owners",
              reg[c3["id"]]["affected"][0]["owner"] == "role.it.security_lead")

        flags = s.process_flags(today=TODAY)
        check("flags: open CAR flags its affected process", "IT.8.4.2" in flags and flags["IT.8.4.2"]["open"] == 1)
        check("flags: severity rolls up to the worst open", flags["IT.8.4.2"]["severity"] == "critical")
        check("flags: a process with no CARs carries no flag", "MS.3.5.2" not in flags)

        # --- notifications ----------------------------------------------
        n = s.notifications(today=TODAY)
        check("notify: the CAR owner is notified", any(i["role"] == "role.it.security_lead"
              and i["kind"] == "owner" for i in n["items"]))
        check("notify: an overdue CAR is counted", n["overdue"] >= 1)

        # --- insights ----------------------------------------------------
        ins = s.insights(today=TODAY)
        titles = " | ".join(f["title"] for f in ins)
        check("insights: surfaces overdue CARs", "overdue" in titles)
        check("insights: surfaces critical open CARs", "critical" in titles)

        # recurrence hotspot: a second open CAR on the same process
        s.raise_car("Second IT issue", "another access gap", "internal_audit", "major",
                    "role.it.security_lead", ["IT.8.4.2"], ACTOR, "second CAR on IT.8.4.2")
        hot = " | ".join(f["title"] for f in s.insights(today=TODAY))
        check("insights: flags a recurrence hotspot", "hotspot" in hot.lower())

        # --- audit integrity --------------------------------------------
        check("audit: the change-control chain is intact after all writes",
              cc.verify_log(cc.EDITS_LOG)["ok"])
    finally:
        cc.set_active_model(active_save)
        cc.MODELS_DIR = models_save


def main():
    run()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
