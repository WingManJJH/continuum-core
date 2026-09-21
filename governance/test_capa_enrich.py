"""Jev CAPA-insight enrichment tests. Plain asserts, hermetic — a canned transport
stands in for Jev (no key, no network); no model writes happen (enrichment only
reads CARs and returns advisory findings).

    python3 governance/test_capa_enrich.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import typesafe as ts  # noqa: E402
import capa_enrich as ce  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


# canned Jev: a CAR flagged "bad" in its title gets high-risk / systemic / symptom /
# expedite answers; anything else gets benign answers. Returns the internal raw shape
# decide() coerces (score / noul / value), so we also exercise that path.
def canned(state, questions):
    bad = "bad" in (state.get("title", "")).lower()
    return {
        "recurrence_risk": {"score": 5 if bad else 1, "confidence": 0.9},
        "systemic": {"noul": 0.9 if bad else 0.1},
        "root_cause_quality": {"noul": 0.2 if bad else 0.9},
        "priority": {"value": "expedite" if bad else "monitor", "confidence": 0.8},
    }


def car(cid, title, root_cause=""):
    return {"id": cid, "title": title, "nonconformance": "something happened",
            "source": "internal_audit", "severity": "major", "state": "investigating",
            "age_days": 10, "root_cause": root_cause, "corrective_action": "",
            "affected": [{"id": "CO.3.2.7", "name": "Verify customer identity"}]}


def main():
    # refuses with no key and no transport
    if not ts.available():
        try:
            ce.jev_insights([car("car.1", "x")])
            check("refuses without Jev access", False)
        except RuntimeError:
            check("refuses without Jev access", True)
    else:
        check("refuses without Jev access (skipped — a key is set in this env)", True)

    # a "bad" CAR with a recorded root cause -> all four Jev findings fire
    bad = car("car.2026.900", "BAD access control gap", root_cause="a person forgot to click approve")
    out = ce.jev_insights([bad], transport=canned)
    titles = " | ".join(f["title"] for f in out)
    check("all findings are tagged source=jev", all(f["source"] == "jev" for f in out))
    check("elevated recurrence risk fires", "recurrence risk" in titles)
    check("systemic cause fires", "systemic" in titles)
    check("symptom-not-cause fires when a root cause is recorded", "symptom" in titles)
    check("expedite suggestion fires", "expediting" in titles)
    check("high recurrence is severity high (score 5)", any(
        f["severity"] == "high" and "recurrence" in f["title"] for f in out))

    # the symptom finding must NOT fire when no root cause is recorded yet
    bad_no_rc = car("car.2026.901", "BAD thing", root_cause="")
    out2 = ce.jev_insights([bad_no_rc], transport=canned)
    check("no symptom finding when root cause is empty",
          not any("symptom" in f["title"] for f in out2))

    # a benign CAR yields no Jev findings (thresholds hold)
    benign = ce.jev_insights([car("car.2026.902", "routine tidy-up", root_cause="clear one-off cause")],
                             transport=canned)
    check("benign CAR produces no findings", benign == [])

    # limit caps how many CARs are sent to Jev (cost control)
    many = [car("car.%03d" % i, "BAD %d" % i, root_cause="rc") for i in range(5)]
    capped = ce.jev_insights(many, transport=canned, limit=2)
    check("limit caps processing (2 CARs -> 8 findings)", len(capped) == 8)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
