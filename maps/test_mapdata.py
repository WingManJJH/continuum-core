"""Process-map data tests (§03 Canvas View). Plain asserts.

    python3 test_mapdata.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import mapdata  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    maps = mapdata.all_maps()
    by_id = {m["id"]: m for m in maps}

    check("all 8 processes mapped", len(maps) == 8)

    co = by_id["CO.3.2.7"]
    check("CO.3.2.7 has 4 tasks in sequence", [t["seq"] for t in co["tasks"]] == [1, 2, 3, 4])
    check("CO header carries guardrail version", co["guardrail"] == "gr.CO.3.2.7.v3")
    check("CO links its risk", any(r["id"] == "rc.kyc_false_verify" for r in co["risks"]))

    t3 = next(t for t in co["tasks"] if t["id"] == "CO.3.2.7.t3")
    check("t3 is agent-bound", "agent.kyc_verifier" in t3["agents"])
    check("t3 shows its escalation branch", t3["escalate_if"] == "risk_score > 0.7"
          and t3["escalation_path"] == "role.ops.support_lead")

    it3 = next(t for t in by_id["IT.8.4.2"]["tasks"] if t["id"] == "IT.8.4.2.t3")
    check("IT.8.4.2.t3 is flagged as a task-level override", it3["override"] is True)
    check("the override step is human-only (no agent)", it3["agents"] == [])

    # every agent-bound task resolves to a guardrail (fail-closed everywhere)
    agent_tasks = [t for m in maps for t in m["tasks"] if t["agents"]]
    check("8 agent-bound steps across the maps", len(agent_tasks) == 8)
    check("every agent step has an effective guardrail", all(t["guardrail"] for t in agent_tasks))

    # editor payload: the effective guardrail is exposed with editable fields
    gf = t3["guardrail_full"]
    check("task carries the full editable guardrail", gf and gf["id"] == "gr.CO.3.2.7"
          and gf["version"] == 3 and "allowed_actions" in gf and "escalate_if" in gf)
    check("task carries data refs for the properties panel",
          t3["inputs"] == ["customer.kyc_doc"] and t3["kpi_refs"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
