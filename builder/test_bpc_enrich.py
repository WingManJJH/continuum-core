"""Jev enrichment tests. Plain asserts, hermetic — a canned transport stands in
for Jev (no key, no network), and the real edit log is reset before and after so
the seed baseline is left clean.

    python3 builder/test_bpc_enrich.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
import store as gov  # noqa: E402
import bpc_enrich as enr  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


# a canned Jev: answers driven by the state so we can assert it saw the process
def canned(state, questions):
    high = "customer" in (state.get("name", "") + state.get("description", "")).lower()
    return {"risk_level": {"score": 5 if high else 2, "confidence": 0.9},
            "customer_facing": {"noul": 0.95 if high else 0.1},
            "automation_potential": {"score": 3}}


def main():
    logs = (cc.EDITS_LOG, cc.EVENTS_LOG)
    for p in logs:
        if os.path.exists(p):
            cc.reset_log(p)
    try:
        s = gov.GovernanceStore()

        # refuses with no key and no transport
        try:
            enr.enrich(s)
            check("refuses without Jev access", False)
        except RuntimeError:
            check("refuses without Jev access", True)

        # dry run classifies but writes nothing
        base = s.graph().get("Process", "CO.3.2.7")["version"]
        dry = enr.enrich(s, transport=canned, limit=2, dry=True)
        check("dry run processes without writing", dry["updated"] == 0 and dry["processed"] == 2
              and s.graph().get("Process", "CO.3.2.7")["version"] == base)

        # real run writes typed answers into custom master data (governed edit)
        res = enr.enrich(s, transport=canned, limit=3)
        check("enrich updates processes", res["updated"] == 3)
        co = s.graph().get("Process", "CO.3.2.7")  # "Verify customer identity (KYC)"
        check("risk_level written as an in-scale score", co["custom"]["risk_level"] == 5)
        check("customer_facing written as a bool", co["custom"]["customer_facing"] is True)
        check("automation_potential written", co["custom"]["automation_potential"] == 3)
        check("provenance recorded", co["custom"]["enriched_by"] == "jev")
        check("version bumped by the governed write", co["version"] == base + 1)
        check("audit chain intact after enrichment", cc.verify_log(cc.EDITS_LOG)["ok"] is True)
    finally:
        for p in logs:
            if os.path.exists(p):
                cc.reset_log(p)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
