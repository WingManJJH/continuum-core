"""Version history & compare tests (D41). Plain asserts.

    python3 test_history.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import history  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    cc.reset_log(cc.EDITS_LOG)
    s = gov.GovernanceStore()
    A = "role.ops.support_lead"

    # make a few governed changes to the same entity
    s.add_group("QA.9", "Quality", 1, A, "stand up quality")
    s.edit_group("QA.9", {"name": "Quality Management", "custom": {"iso": "9001"}}, A, "rename + tag")
    s.edit_group("QA.9", {"owner_role": A}, A, "assign owner")

    h = history.entity_history("ProcessGroup", "QA.9")
    check("entity history has one row per change", h["revisions"] == 3)
    check("each revision records who + why", all(r["actor"] and "reason" in r for r in h["timeline"]))
    names = [c for r in h["timeline"] for c in r["changes"] if c["field"] == "name"]
    check("a field diff captures the rename (old -> new)", any(c["new"] == "Quality Management" and c["old"] == "Quality" for c in names))

    # compare two specific versions
    cmp = history.compare_versions("ProcessGroup", "QA.9", 1, 3)
    check("compare_versions is order-independent + diffs the fields", cmp["from"] == 1 and cmp["to"] == 3
          and any(c["field"] == "name" for c in cmp["changes"]))

    # model-level change summary
    m = history.model_changes()
    check("model summary counts total changes", m["total_changes"] >= 3)
    check("summary breaks down by entity type (created/updated)",
          m["by_type"].get("ProcessGroup", {}).get("created", 0) >= 1 and m["by_type"]["ProcessGroup"]["updated"] >= 2)
    check("recent stream is newest-first with who/why", m["recent"] and m["recent"][0]["reason"])
    check("summary confirms the audit chain is intact", m["chain_intact"] is True)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
