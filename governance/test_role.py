"""Role master-data write-path tests (D33). Plain asserts.

HumanRole is master data referenced across the graph (owners, performers,
escalation paths). Authoring / renaming / retiring a role goes through the same
versioned, hash-chained governance write path, and a role in use cannot be
retired out from under the things that point at it.

    python3 test_role.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "maps"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import mapdata  # noqa: E402

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

    # 0. the master data is there (seeded)
    check("Graph carries the seeded HumanRole master data", len(cc.Graph().all("HumanRole")) >= 21)

    # 1. author a new role
    r = s.add_role("role.ops.qa_reviewer", "QA Reviewer", A, "new QA function",
                   raci={"responsible": True, "consulted": True}, skills=["iso9001", "audit"])
    check("add_role mints a versioned active role", r["id"] == "role.ops.qa_reviewer" and r["version"] == 1 and r["status"] == "active")
    check("raci + skills captured", r["raci"] == {"responsible": True, "consulted": True} and "iso9001" in r["skills"])
    check("the new role is live in the graph (audited)", cc.Graph().get("HumanRole", "role.ops.qa_reviewer") is not None)

    # 2. validation guards
    check("a bad role id is refused", rejects(lambda: s.add_role("Ops Team", "x", A, "y"), "role.dept.name"))
    check("a missing name is refused", rejects(lambda: s.add_role("role.ops.blank", "", A, "y"), "name is required"))
    check("a duplicate role is refused", rejects(lambda: s.add_role("role.ops.qa_reviewer", "dup", A, "y"), "already exists"))

    # 3. edit: rename (id immutable), version bumps
    e = s.edit_role("role.ops.qa_reviewer", {"name": "Quality Reviewer"}, A, "clearer title")
    check("edit_role renames + bumps the version", e["name"] == "Quality Reviewer" and e["version"] == 2)
    check("a non-editable field (incl. id) is refused", rejects(lambda: s.edit_role("role.ops.qa_reviewer", {"id": "role.x"}, A, "y"), "not editable"))

    # 4. usage lookup + retire guard
    refs = s.role_refs(cc.Graph(), "role.ops.support_lead")
    check("role_refs finds where a seeded role is used", (len(refs["as_owner"]) + len(refs["as_performer"]) + len(refs["as_escalation"])) >= 1)
    check("a role in use cannot be retired", rejects(lambda: s.remove_role("role.ops.support_lead", A, "y"), "in use"))
    # the QA role we just made is unused -> can retire
    dep = s.remove_role("role.ops.qa_reviewer", A, "not needed after all")
    check("an unused role retires (deprecated, versioned)", dep["status"] == "deprecated" and dep["version"] == 3)
    check("a retired role drops out of the active master list", cc.Graph().get("HumanRole", "role.ops.qa_reviewer")["status"] == "deprecated")

    # 5. mapdata.roles feeds the panel + drawer with usage
    s.add_role("role.ops.qa_reviewer2", "QA Reviewer 2", A, "demo")
    rl = mapdata.roles(cc.Graph())
    by_id = {x["id"]: x for x in rl}
    check("mapdata.roles lists active roles with usage", "role.ops.support_lead" in by_id and by_id["role.ops.support_lead"]["in_use"] is True)
    check("a brand-new unused role reads in_use=False", by_id["role.ops.qa_reviewer2"]["in_use"] is False)
    check("used_by carries owner/performer/escalation/objective keys",
          set(by_id["role.ops.support_lead"]["used_by"]) == {"owner", "performer_processes", "performer_tasks", "escalation", "objectives"})

    # leave the shared log clean for order-independent reader tests
    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
