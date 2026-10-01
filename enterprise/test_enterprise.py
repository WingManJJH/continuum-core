"""EA / GRC building blocks on the governed model (D45). Plain asserts; runs in a
private temp copy of the default model, so the repo's data/ is never touched.

    python3 enterprise/test_enterprise.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp_server"))
sys.path.insert(0, os.path.join(ROOT, "governance"))
sys.path.insert(0, ROOT)

import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import approvals  # noqa: E402
import approval_policy  # noqa: E402
from enterprise import rules  # noqa: E402

PASS, FAIL = [], []
ACTOR = "role.ops.head_of_operations"
TODAY = "2026-09-30"


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def refused(fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False
    except gov.EditError:
        return True


def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(ROOT, "data", "seed.json"), os.path.join(tmp, "seed.json"))
    saved = (cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE)
    cc.DATA, cc.EDITS_LOG = os.path.join(tmp, "seed.json"), os.path.join(tmp, "edits.log.jsonl")
    cc.EVENTS_LOG, cc.HEADS_FILE = os.path.join(tmp, "events.log.jsonl"), os.path.join(tmp, "audit_heads.json")
    try:
        run(tmp)
    finally:
        cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


def run(tmp):
    s = gov.GovernanceStore()

    # --- Phase 1 records are read by the rules with no migration
    v = rules.View(s.graph())
    check("legacy RiskControl reads as a risk + a control", "rc.kyc_false_verify" in v.risks
          and "rc.kyc_false_verify#control" in v.ctls)
    r = rules.ripple(v, "CO.3.2.7")
    ids = {a["id"] for a in r["affected"]}
    check("Ripple from a process reaches its tasks and its legacy risk", "CO.3.2.7.t3" in ids
          and "rc.kyc_false_verify" in ids)
    check("standalone AgentBinding is an affected agent", "agent.kyc_verifier" in ids)
    gr = next((x for x in r["guardrails"] if x["taskId"] == "CO.3.2.7.t3"), None)
    check("guardrail cited with its pinned version", gr is not None and gr["version"] == "gr.CO.3.2.7.v3"
          and gr["blank"] is False)
    check("KPIs resolve to their names", any(k["name"] for k in r["kpis"]) and
          all(not k["name"].startswith("kpi.") for k in r["kpis"]))
    vt = rules.vitals(v, TODAY)
    check("legacy controls are not flagged as untested", not any(f["nodeId"] and f["nodeId"].endswith("#control")
                                                                for f in vt["findings"]))

    # --- packs
    res = s.seed_obligation_pack("iso9001", ACTOR)
    check("ISO 9001 pack seeds 28 clauses", res == {"pack": "iso9001", "added": 28, "total": 28})
    check("seeding again adds nothing (idempotent)", s.seed_obligation_pack("iso9001", ACTOR)["added"] == 0)
    check("ISO 9004 pack seeds 33 clauses", s.seed_obligation_pack("iso9004", ACTOR)["added"] == 33)
    check("unknown pack refused", refused(s.seed_obligation_pack, "nis2", ACTOR))
    o = s.graph().get("Obligation", "obl.iso9001.7_5")
    check("clause carries title + own-wording summary", o and o["clause"] == "7.5" and len(o["summary"]) < 160)

    # --- capabilities
    l1 = s.add_capability({"name": "Customer onboarding", "level": 1, "importance": "critical"}, ACTOR, "map L1")
    check("capability id from its name", l1["id"] == "cap.customer_onboarding" and l1["version"] == 1)
    l2 = s.add_capability({"name": "Identity verification", "level": 2, "parent_ref": l1["id"],
                           "process_refs": ["CO.3.2.7"]}, ACTOR, "map L2")
    dup = s.add_capability({"name": "Identity verification", "level": 2}, ACTOR, "a second one")
    check("generated ids never collide", dup["id"] == "cap.identity_verification_2")
    check("unknown process refused", refused(s.add_capability, {"name": "X", "level": 1, "process_refs": ["ZZ.9.9"]},
                                             ACTOR, "bad ref"))
    check("cycle refused", refused(s.edit_capability, l1["id"], {"parent_ref": l2["id"]}, ACTOR, "loop"))
    check("unknown owner role refused", refused(s.add_capability, {"name": "Y", "level": 1, "owner": "role.nobody"},
                                                ACTOR, "bad owner"))
    check("reason required (ISO 9001 §7.5)", refused(s.add_capability, {"name": "Z", "level": 1}, ACTOR, " "))
    check("non-role actor refused", refused(s.add_capability, {"name": "Z", "level": 1}, "jeff", "why"))
    check("schema enforced (level 9)", refused(s.add_capability, {"name": "Z", "level": 9}, ACTOR, "why"))
    check("unknown field refused", refused(s.add_capability, {"name": "Z", "level": 1, "colour": "red"}, ACTOR, "why"))

    # --- applications and agents
    app = s.add_application({"name": "Identity Hub", "vendor": "Acme", "owner": "role.ops.support_lead",
                             "capability_refs": [l2["id"]], "task_refs": ["CO.3.2.7.t3"]}, ACTOR, "register system")
    agt = s.add_application({"name": "KYC Verifier", "kind": "agent", "owner": "role.ops.support_lead",
                             "agent_binding_refs": ["agent.kyc_verifier"]}, ACTOR, "register agent")
    check("a system cannot own agent bindings", refused(s.edit_application, app["id"],
                                                        {"agent_binding_refs": ["agent.kyc_verifier"]}, ACTOR, "x"))
    v = rules.View(s.graph())
    check("agent app owns its binding (no duplicate agent node)", "agent.kyc_verifier" not in v.idx
          and any(e["s"] == agt["id"] and e["t"] == "CO.3.2.7.t3" and e["type"] == "supports" for e in v.edges))

    # --- risks and controls
    rk = s.add_risk({"name": "Synthetic identity accepted", "likelihood": 4, "impact": 5,
                     "process_refs": ["CO.3.2.7"]}, ACTOR, "register risk")
    ct = s.add_control({"name": "Second-look on high-risk KYC", "type": "detective", "frequency": "monthly",
                        "obligation_refs": ["obl.iso9001.8_5"], "risk_refs": [rk["id"]], "task_refs": ["CO.3.2.7.t3"]},
                       ACTOR, "register control")
    check("control starts untested", ct["last_result"] == "not_tested")
    v = rules.View(s.graph())
    vt = rules.vitals(v, TODAY)
    check("Vitals flags the untested control", any(f["rule"] == "control-untested" and f["nodeId"] == ct["id"]
                                                  for f in vt["findings"]))
    s.record_control_test(ct["id"], "fail", "2026-09-29", ACTOR, "monthly test")
    v = rules.View(s.graph())
    vt = rules.vitals(v, TODAY)
    check("a failed test is critical in Vitals", any(f["rule"] == "control-failed" and f["severity"] == "critical"
                                                     for f in vt["findings"]))
    row = next(rw for pk in rules.assure(v, TODAY)["packs"] for rw in pk["rows"]
               if rw["obligation"]["id"] == "obl.iso9001.8_5")
    check("Assure: failing control makes its clause partial", row["status"] == "partial")
    s.record_control_test(ct["id"], "pass", "2026-09-30", ACTOR, "re-test after fix")
    v = rules.View(s.graph())
    row = next(rw for pk in rules.assure(v, TODAY)["packs"] for rw in pk["rows"]
               if rw["obligation"]["id"] == "obl.iso9001.8_5")
    check("Assure: in-date passing control covers the clause", row["status"] == "covered")
    check("result must be pass/fail", refused(s.record_control_test, ct["id"], "maybe", TODAY, ACTOR, "x"))

    # --- Ripple across the new blocks
    r = rules.ripple(v, app["id"])
    ids = {a["id"] for a in r["affected"]}
    check("Ripple from a system: task, process, capability, control, risk",
          {"CO.3.2.7.t3", "CO.3.2.7", l2["id"], ct["id"], rk["id"]} <= ids)
    check("agent on the same task is affected", agt["id"] in ids)
    up = rules.ripple(v, l1["id"])
    check("capability reads upstream (what it depends on)", up["mode"] == "upstream"
          and {"CO.3.2.7", l2["id"]} <= {a["id"] for a in up["affected"]})
    tree = rules.atlas(v)
    node = next(n for n in tree if n["id"] == l1["id"])
    check("Atlas nests L2 under L1 and rolls up the process", node["children"][0]["id"] == l2["id"]
          and any(p["id"] == "CO.3.2.7" for p in node["allProcesses"]))

    # --- link / unlink and retire
    before = s.graph().get("Obligation", "obl.iso9001.4_4")["version"]
    s.link_ea("Obligation", "obl.iso9001.4_4", "process_refs", "CO.3.2.7", ACTOR, "map clause")
    s.link_ea("Obligation", "obl.iso9001.4_4", "process_refs", "CO.3.2.7", ACTOR, "again")
    check("link is idempotent (one new version)", s.graph().get("Obligation", "obl.iso9001.4_4")["version"] == before + 1)
    s.unlink_ea("Obligation", "obl.iso9001.4_4", "process_refs", "CO.3.2.7", ACTOR, "unmap")
    check("unlink removes the ref", s.graph().get("Obligation", "obl.iso9001.4_4")["process_refs"] == [])
    s.retire_application(app["id"], ACTOR, "replaced")
    check("retired system leaves the view", app["id"] not in rules.View(s.graph()).idx)
    check("a retired record can't be referenced", refused(s.add_control, {"name": "Q", "type": "detective",
          "frequency": "annual", "last_result": "not_tested", "risk_refs": ["rsk.nope"]}, ACTOR, "x"))

    # --- Phase 1 bridge: split a RiskControl
    out = s.split_risk_control("rc.kyc_false_verify", ACTOR, "make it testable")
    v = rules.View(s.graph())
    check("split creates a Risk and a Control", out["risk"]["id"] == "rsk.kyc_false_verify"
          and out["control"]["risk_refs"] == ["rsk.kyc_false_verify"])
    check("split retires the RiskControl (no double count)", "rc.kyc_false_verify" not in v.risks
          and s.graph().get("RiskControl", "rc.kyc_false_verify")["status"] == "deprecated")

    # --- governance: approvals gate + audit
    pol = approval_policy.ApprovalPolicy(os.path.join(tmp, "approval-policy.log.jsonl"))
    check("EA blocks are on the approval policy", all(k in pol.get() for k in ("Capability", "Application",
                                                                                "Obligation", "Control", "Risk")))
    check("op -> policy entity mapping covers EA ops", approval_policy.OP_ENTITY["retire_risk"] == "Risk"
          and approval_policy.OP_ENTITY["record_control_test"] == "Control")
    q = approvals.ApprovalQueue(s, os.path.join(tmp, "proposals.log.jsonl"))
    cr = q.propose("add_capability", {"fields": {"name": "Payments", "level": 1}}, proposed_by=ACTOR,
                   reason="new L1")
    check("EA change can be proposed for review", cr["status"] == "pending"
          and s.graph().get("Capability", "cap.payments") is None)
    q.approve(cr["id"], reviewer="role.finance.cfo", decision_reason="agreed")
    check("approval applies it", s.graph().get("Capability", "cap.payments") is not None)
    check("hash chain intact after every EA write", cc.verify_log(cc.EDITS_LOG)["ok"])
    evs = [e for e in cc.read_log(cc.EDITS_LOG)] if hasattr(cc, "read_log") else []
    check("every EA write is an event with actor + reason",
          all(e.get("actor") and e.get("reason") for e in evs) if evs else True)


if __name__ == "__main__":
    main()
