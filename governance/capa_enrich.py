"""
Enrich the corrective-action insights with Jev (TypeSafe System One).

CAPAStore.insights() is deterministic — overdue, critical, recurrence hotspots,
aging, a root cause repeating verbatim across CARs. Useful, but blind to meaning:
it can't tell whether a *root cause reads like a symptom*, whether a nonconformity
is *systemic* rather than a one-off, or how likely it is to *recur* once closed as
planned. Those are semantic judgments — exactly what a System One model answers as
typed values (not prose).

For each open CAR we ask Jev a few independent typed questions in one pass and turn
the answers into advisory findings, tagged `source: "jev"`, that sit alongside the
deterministic ones. Jev only *adds* insight; it never changes a CAR, and the
deterministic register stands on its own. Env-gated exactly like the LLM/enrichment
seams: with no CONTINUUM_TYPESAFE_API_KEY and no injected transport it refuses, and
a `transport(state, questions) -> dict` runs it hermetically for tests.

Design follows the TypeSafe skill + live docs: score levels describe concrete
situations (not degrees), one condition per noul, choice options carry descriptions,
and every threshold is applied here in code — Jev supplies the judgment, policy
stays explicit and ours.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import typesafe as ts  # noqa: E402

# Independent judgments over the same CAR state — asked together (one parallel pass).
QUESTIONS = [
    {
        "id": "recurrence_risk", "kind": "score", "scale": [1, 5],
        "prompt": "How likely is this same nonconformity to recur after it is closed as currently planned?",
        "levels": [
            "A one-off slip with a clear immediate cause; once corrected it is very unlikely to happen again.",
            "Unlikely to recur — the cause is understood and the fix removes it.",
            "Could recur — the cause is only partly understood, or the fix is a procedure/reminder that may not hold.",
            "Likely to recur — the corrective action treats the symptom, or the cause is built into how the process works.",
            "Almost certain to recur without deeper change — a known pattern, or the same failure has happened before.",
        ],
    },
    {
        "id": "systemic", "kind": "noul",
        "prompt": "Is this nonconformity systemic — rooted in how the process, its controls, or its systems are designed?",
        "true": "Rooted in the process/control/system design; it would likely affect other cases or other processes too.",
        "false": "An isolated one-off — a single human slip or special-cause event unlikely to generalize.",
    },
    {
        "id": "root_cause_quality", "kind": "noul",
        "prompt": "Does the recorded root cause describe an underlying cause, rather than restating the symptom?",
        "true": "Names an underlying cause (why it happened) that a corrective action could remove.",
        "false": "Missing, or it just restates what went wrong (the symptom) without explaining why.",
    },
    {
        "id": "priority", "kind": "choice", "options": ["expedite", "normal", "monitor"],
        "prompt": "Given the severity, customer/compliance impact, and how long it has been open, what priority should this corrective action get?",
        "option_desc": {
            "expedite": "High impact or fast-moving; it should jump the queue and be contained and closed first.",
            "normal": "Handle in the normal corrective-action cadence.",
            "monitor": "Low impact; keep it open and watch it, but it need not consume priority effort now.",
        },
    },
]

# Thresholds — applied here, on our data and consequences (skill: keep policy explicit).
RECURRENCE_HIGH = 4.0      # 1..5 internal scale
SYSTEMIC_YES = 0.6         # noul; acting on it means "consider preventive action", cheap to be wrong
SYMPTOM_MAX = 0.4          # root_cause_quality below this reads like a symptom


def _state(c: dict) -> dict:
    """The CAR context Jev judges — observed facts only, no inferred fields."""
    return {
        "id": c.get("id"), "title": c.get("title", ""),
        "nonconformance": c.get("nonconformance", ""),
        "source": c.get("source", ""), "severity": c.get("severity", ""),
        "state": c.get("state", ""), "age_days": c.get("age_days"),
        "root_cause": c.get("root_cause", ""),
        "corrective_action": c.get("corrective_action", ""),
        "affected_processes": [a.get("name", a.get("id")) for a in c.get("affected", [])],
    }


def _finding(severity, title, detail, recommendation):
    return {"source": "jev", "severity": severity, "title": title,
            "detail": detail, "recommendation": recommendation}


def jev_insights(cars: list[dict], transport=None, limit: int = 15) -> list[dict]:
    """Ask Jev typed questions about each open CAR and return advisory findings
    (source='jev'), same shape as the deterministic insights. Refuses if Jev is
    unavailable. `cars` are enriched open-CAR rows (CAPAStore.open_cars())."""
    if not ts.available(transport):
        raise RuntimeError("no Jev access — set CONTINUUM_TYPESAFE_API_KEY (or inject a transport)")
    out = []
    for c in (cars or [])[:limit]:
        cid = c.get("id", "?")
        ans = ts.decide(_state(c), QUESTIONS, transport=transport)
        rec = ans["recurrence_risk"]["score"]
        if rec is not None and rec >= RECURRENCE_HIGH:
            out.append(_finding(
                "high" if rec >= 4.5 else "medium",
                "Jev: elevated recurrence risk — " + cid,
                "Jev rates recurrence risk %.1f/5 for %s (%s)." % (rec, cid, c.get("title", "")),
                "Strengthen the preventive action — a reminder or procedure may not hold; remove the underlying cause."))
        sysp = ans["systemic"]["noul"]
        if sysp is not None and sysp >= SYSTEMIC_YES:
            out.append(_finding(
                "medium",
                "Jev: likely a systemic cause — " + cid,
                "Jev estimates a %.0f%% chance this is systemic (process/control design), not a one-off." % (sysp * 100),
                "Treat the class of problem: add preventive action across the value stream, not just this instance."))
        rcq = ans["root_cause_quality"]["noul"]
        if c.get("root_cause", "").strip() and rcq is not None and rcq <= SYMPTOM_MAX:
            out.append(_finding(
                "medium",
                "Jev: root cause reads like a symptom — " + cid,
                "Jev estimates only a %.0f%% chance the recorded root cause names an underlying cause." % (rcq * 100),
                "Re-do the root-cause analysis (e.g. 5-whys) so the corrective action targets the cause, not the symptom."))
        pri = ans["priority"]["value"]
        if pri == "expedite":
            out.append(_finding(
                "high",
                "Jev: suggests expediting — " + cid,
                "Given severity, impact, and age, Jev places %s in the expedite tier." % cid,
                "Contain now and prioritize this CAR ahead of the normal cadence."))
    return out


def available(transport=None) -> bool:
    return ts.available(transport)
