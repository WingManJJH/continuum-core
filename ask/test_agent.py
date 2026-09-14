"""Ask-the-Agent tests (D18). Plain asserts.

    python3 test_agent.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import agent as ag  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    a = ag.Agent()

    # 1. every curated example resolves to a matched, executed query
    for utt in a.examples():
        r = a.ask(utt)
        check(f"example resolves + runs: {utt[:38]}", r["matched"] and r["cql"] and "error" not in r)

    # 2. the query is genuinely read-only (the receipt never mutates)
    r = a.ask("which processes have no guardrail?")
    check("read-only receipt: no write verbs", not any(
        w in r["cql"].upper() for w in ("INSERT", "UPDATE", "DELETE", "APPEND", "CREATE", "SET ")))

    # 3. grounded answers against the seed's known facts
    r = a.ask("which processes do not trace to a strategic objective?")
    check("planted dangling process HR.7.2.5 is found", r["n"] == 1 and r["rows"][0]["id"] == "HR.7.2.5")

    r = a.ask("which guardrails are unreviewed defaults?")
    check("7 unreviewed default guardrails", r["n"] == 7 and all("gr." in row["id"] for row in r["rows"]))

    r = a.ask("which tasks have an agent bound?")
    check("8 agent steps found", r["n"] == 8)

    r = a.ask("which KPIs are off target?")
    check("KPI breach detection returns rows", r["n"] >= 1 and r["intent"] == "kpis_breaching")

    r = a.ask("which APQC domains does the model cover?")
    check("8 APQC domains", "8 APQC domains" in r["answer"])

    r = a.ask("which processes have the lowest maturity?")
    check("lowest-maturity ordered ascending", r["rows"][0]["maturity_score"] <= r["rows"][-1]["maturity_score"])

    r = a.ask("which guardrails allow a high-stakes action?")
    check("high-stakes scan runs (clean seed)", r["intent"] == "high_stakes_guardrails" and r["n"] == 0)

    # 4. an id in the question -> entity detail lookup
    r = a.ask("show me everything about gr.CO.3.2.7")
    check("entity detail by id", r["matched"] and r["intent"] == "entity_detail"
          and any(row["field"] == "allowed_actions" for row in r["rows"]))
    r = a.ask("tell me about CO.3.2.7")
    check("process id detail", r["intent"] == "entity_detail" and "Process CO.3.2.7" in r["answer"])

    # 5. unmatched question -> honest auth-gated seam note + suggestions
    r = a.ask("write me a poem about buffers")
    check("unmatched question is honest, not faked",
          not r["matched"] and "auth-gated" in r["answer"] and len(r["suggestions"]) >= 5)
    check("unmatched names the LLMPlanner seam", "LLMPlanner" in r["note"])

    # 6. the LLM planner seam is declared but refuses
    try:
        ag.LLMPlanner().plan("anything"); llm = False
    except RuntimeError:
        llm = True
    check("LLMPlanner is declared but auth-gated (refuses)", llm)

    # 7. empty question handled
    check("empty question returns suggestions, no crash", a.ask("")["suggestions"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
