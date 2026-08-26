"""Conformance Check tests (Phase 3). Plain asserts.

    python3 test_conformance.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import conformance as cf  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    signals, events = cf.gather()
    g = cc.Graph()
    report = cf.ConformanceCheck(g).run(signals, events)
    c = report["counts"]

    check("finds the stale guardrail (agent citing v2 vs v3)", c.get("stale_guardrail") == 1)
    check("finds the off-model agent action", c.get("off_model_action") == 1)
    check("finds the coverage gap", c.get("coverage_gap") == 1)
    check("finds the undocumented step (t5)", c.get("undocumented_step") == 1)
    check("finds the shadow process (XX.9.9.9)", c.get("shadow_process") == 1)
    check("exactly 5 findings — conformant cases produce none", report["n_findings"] == 5)
    check("every finding requires human review (§06: nothing auto-applied)",
          all(f["requires_human_review"] for f in report["findings"]))

    # §06 invariant: the Check does not mutate the model
    before = g.get("GuardrailPolicy", "gr.CO.3.2.7")["version"]
    cf.ConformanceCheck(g).run(signals, events)
    after = cc.Graph().get("GuardrailPolicy", "gr.CO.3.2.7")["version"]
    check("conformance never writes to the model", before == after)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
