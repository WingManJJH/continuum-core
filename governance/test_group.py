"""Process-hierarchy + master-data write-path tests (D39). Plain asserts.

    python3 test_group.py
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


def rejects(fn, needle=""):
    try:
        fn(); return False
    except gov.EditError as e:
        return needle in str(e)


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    A = "role.ops.support_lead"

    # 0. seeded L1 domain groups
    check("Graph carries the seeded L1 process groups", len([x for x in cc.Graph().all("ProcessGroup")]) >= 8)

    # 1. add an L2 group under a domain
    grp = s.add_group("CO.3", "Customer onboarding group", 2, A, "L2", parent_ref="CO", owner_role=A)
    check("add_group makes a versioned L2 node", grp["id"] == "CO.3" and grp["level"] == 2 and grp["parent_ref"] == "CO" and grp["version"] == 1)
    check("bad group id refused", rejects(lambda: s.add_group("co3", "x", 2, A, "y"), "CO or CO.3"))
    check("duplicate group refused", rejects(lambda: s.add_group("CO.3", "dup", 2, A, "y"), "already exists"))
    check("unknown parent refused", rejects(lambda: s.add_group("ZZ.9", "x", 2, A, "y", parent_ref="ZZ"), "unknown parent"))

    # 2. edit a group — rename + owner + custom master data
    e = s.edit_group("CO.3", {"name": "Onboarding", "custom": {"iso_clause": "8.2", "criticality": "high"}}, A, "curate")
    check("edit_group renames + stores custom metadata + bumps version",
          e["name"] == "Onboarding" and e["custom"]["iso_clause"] == "8.2" and e["version"] == 2)
    check("non-editable group field refused", rejects(lambda: s.edit_group("CO.3", {"status": "x"}, A, "y"), "not editable"))
    check("a group can't be its own parent", rejects(lambda: s.edit_group("CO.3", {"parent_ref": "CO.3"}, A, "y"), "own parent"))

    # 3. retire guard — a group with children can't be retired
    check("group with children can't be retired", rejects(lambda: s.remove_group("CO", A, "y"), "child"))
    s.add_group("QA.1", "Quality (empty)", 1, A, "temp")
    dep = s.remove_group("QA.1", A, "not needed")
    check("an empty group retires (deprecated)", dep["status"] == "deprecated")

    # 4. edit_process — parent / objective links / custom master data
    r = s.edit_process("CO.3.2.7", {"parent_ref": "CO.3",
                                    "objective_refs": ["obj.reduce_onboarding_friction"],
                                    "custom": {"sox": True, "region": "EMEA"}}, A, "align + reparent")
    check("edit_process reparents + links objectives + stores custom", r["parent_ref"] == "CO.3"
          and "obj.reduce_onboarding_friction" in r["objective_refs"] and r["custom"]["region"] == "EMEA")
    check("edit_process rejects a non-editable field", rejects(lambda: s.edit_process("CO.3.2.7", {"guardrail_ref": "x"}, A, "y"), "not editable"))
    check("edit_process rejects an unknown parent", rejects(lambda: s.edit_process("CO.3.2.7", {"parent_ref": "ZZ"}, A, "y"), "unknown parent"))

    check("audit chain intact after hierarchy edits", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
