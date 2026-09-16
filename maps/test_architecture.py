"""Process-architecture (L1–L5 hierarchy) aggregation tests (D39). Plain asserts.

    python3 test_architecture.py
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
import mapdata  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    cc.reset_log(cc.EDITS_LOG)

    a = mapdata.architecture()
    check("8 L1 roots, every process placed", len(a["roots"]) == 8 and a["process_total"] == 8)
    check("no orphan processes (all parented by seed)", a["orphans"] == [])
    co = next(n for n in a["roots"] if n["id"] == "CO")
    check("a root carries its level + child processes", co["level"] == 1 and any(p["id"] == "CO.3.2.7" for p in co["processes"]))
    check("flat group list is present for the master-data panel", len(a["groups"]) == 8 and all("process_count" in x for x in a["groups"]))

    # add an L2 layer and reparent a process into it
    s = gov.GovernanceStore()
    A = "role.ops.support_lead"
    s.add_group("CO.3", "Onboarding", 2, A, "L2", parent_ref="CO")
    s.edit_process("CO.3.2.7", {"parent_ref": "CO.3", "custom": {"tier": "1"}}, A, "reparent")

    a2 = mapdata.architecture()
    co2 = next(n for n in a2["roots"] if n["id"] == "CO")
    l2 = next((c for c in co2["children"] if c["id"] == "CO.3"), None)
    check("a new L2 group nests under its L1 parent", l2 is not None and l2["level"] == 2)
    check("the reparented process now hangs under the L2 group", any(p["id"] == "CO.3.2.7" for p in l2["processes"]))
    check("custom master-data surfaces on the process card", any(p.get("custom", {}).get("tier") == "1" for p in l2["processes"]))

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
