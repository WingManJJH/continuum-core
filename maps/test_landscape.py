"""Process-landscape / repository aggregation tests (D29). Plain asserts.

    python3 test_landscape.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import mapdata  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    L = mapdata.landscape()

    # 1. every active process placed under an APQC domain
    check("8 processes across 8 domains", L["processes_total"] == 8 and len(L["domains"]) == 8)
    check("domains carry a readable name", any(d["name"] != d["code"] for d in L["domains"]))
    total_in_domains = sum(len(d["processes"]) for d in L["domains"])
    check("every process appears exactly once in the house", total_in_domains == L["processes_total"])

    # 2. per-process stats
    co = next(p for d in L["domains"] for p in d["processes"] if p["id"] == "CO.3.2.7")
    check("process card has steps + owner", co["steps"] >= 1 and co["owner"].startswith("role."))
    check("CO.3.2.7 has an agent step + a reviewed guardrail", co["agent_steps"] >= 1 and co["reviewed"] is True)
    fn = next(p for d in L["domains"] for p in d["processes"] if p["id"] == "FN.9.3.1")
    check("an unreviewed-default process reads reviewed=False", fn["reviewed"] is False)

    # 3. catalogs thread across processes
    cats = L["catalogs"]
    check("roles catalog is populated + name-labeled", len(cats["roles"]) >= 1 and all("name" in r and "count" in r for r in cats["roles"]))
    check("roles are sorted by usage (desc)", [r["count"] for r in cats["roles"]] == sorted([r["count"] for r in cats["roles"]], reverse=True))
    check("a role lists the processes that use it", all(r["count"] == len(r["processes"]) for r in cats["roles"]))
    check("KPIs catalog present + labeled", len(cats["kpis"]) >= 1 and all(k.get("name") for k in cats["kpis"]))
    check("risks catalog lists RiskControls with their process", len(cats["risks"]) == 3 and all(x["process"] for x in cats["risks"]))

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
