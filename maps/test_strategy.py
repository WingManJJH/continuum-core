"""Strategy layer — OKR / X-matrix / alignment + write paths (D40). Plain asserts.

    python3 test_strategy.py
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
import strategy as strat  # noqa: E402

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

    # 1. assembly
    m = strat.strategy()
    check("enterprise mission/vision/values present", m["enterprise"] and m["enterprise"]["mission"] and len(m["enterprise"]["values"]) >= 3)
    check("objectives typed breakthrough vs annual", len(m["breakthroughs"]) >= 1 and len(m["annuals"]) >= 1)
    o0 = next(o for o in m["objectives"] if o["id"] in m["breakthroughs"])
    check("a breakthrough objective carries KPIs with fulfilment status", o0["kpis"] and all("status" in k for k in o0["kpis"]))
    check("KPIs (key results) link to supporting processes", len(o0["processes"]) >= 1)
    check("a KPI hierarchy surfaces (a root KPI has children)", any(k.get("children") for k in m["kpi_roots"]))
    check("gaps are surfaced honestly", "kpis_off_target" in m["gaps"] and len(m["gaps"]["kpis_off_target"]) >= 1)

    # 2. the X-matrix KPIs ARE the process KPIs (same ids), and correlations exist
    xm = strat.xmatrix()
    check("X-matrix has breakthrough rows + annual cols + KPI results + initiatives",
          len(xm["breakthroughs"]) >= 1 and len(xm["annuals"]) >= 1 and len(xm["kpis"]) >= 1 and len(xm["initiatives"]) >= 1)
    check("X-matrix KPIs are the same governed KPI ids the processes move",
          all(k["id"].startswith("kpi.") for k in xm["kpis"]))
    check("correlations connect annual objectives to breakthroughs / KPIs", len(xm["correlations"]) >= 2)
    check("an off-target X-matrix KPI is flagged", any(k["status"] == "off_target" for k in xm["kpis"]))

    # 3. write paths — versioned + audited
    s = gov.GovernanceStore()
    A = "role.ops.support_lead"
    e = s.edit_objective(o0["id"], {"type": "breakthrough", "applies_to_levels": [1, 2, 3]}, A, "confirm breakthrough")
    check("edit_objective sets type + applies-to levels (versioned)", e["type"] == "breakthrough" and e["applies_to_levels"] == [1, 2, 3] and e["version"] >= 3)
    kid = o0["kpis"][0]["id"]
    ek = s.edit_kpi(kid, {"target": 3.5}, A, "tighten target")
    check("edit_kpi updates a target (versioned)", ek["target"] == 3.5 and ek["version"] >= 2)
    it = s.add_initiative("init.test_priority", "Test priority", A, "new priority",
                          objective_refs=[o0["id"]], process_refs=["CO.3.2.7"])
    check("add_initiative mints an improvement priority", it["id"] == "init.test_priority" and it["objective_refs"] == [o0["id"]])
    check("duplicate initiative refused", rejects(lambda: s.add_initiative("init.test_priority", "d", A, "y"), "already exists"))
    s.edit_enterprise({"vision": "A governed operating system for every organization."}, A, "sharpen vision")
    check("edit_enterprise updates the vision", strat.strategy()["enterprise"]["vision"].startswith("A governed"))
    check("audit chain intact after strategy edits", cc.verify_log(cc.EDITS_LOG)["ok"] is True)

    cc.reset_log(cc.EDITS_LOG)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)




if __name__ == "__main__":
    main()
