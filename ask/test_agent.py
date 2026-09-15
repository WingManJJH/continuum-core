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

    # widened question set (D24): risk coverage, RACI, ownership, rate limits, models
    r = a.ask("which processes have no risk control?")
    check("5 processes lack a risk control", r["n"] == 5 and "HR.7.2.5" in [x["id"] for x in r["rows"]])
    r = a.ask("who owns each process?")
    check("8 process owners listed", r["intent"] == "process_owners" and r["n"] == 8
          and all(x.get("owner_role") for x in r["rows"]))
    r = a.ask("which roles are accountable?")
    check("accountable roles found via RACI", r["intent"] == "accountable_roles" and r["n"] >= 1)
    r = a.ask("which guardrails have no rate limit?")
    check("rate-limit coverage runs (seed all bounded)", r["intent"] == "unbounded_guardrails" and r["n"] == 0)
    r = a.ask("which models run the agents?")
    check("agent model tally", r["intent"] == "agent_models" and "claude-opus-4-8" in r["answer"])

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

    # 6. the LLM planner seam refuses when no key/transport is present
    eng = ag.QueryEngine()
    try:
        ag.LLMPlanner(eng).plan("anything"); llm = False
    except RuntimeError:
        llm = True
    check("LLMPlanner refuses with no key (auth-gated)", llm)
    check("LLMPlanner reports unavailable with no key", not ag.LLMPlanner(eng).available())

    # 7. plan validation whitelists to a bounded, read-only plan
    good = ag.validate_plan({"from": "Process", "where": [{"op": "absent", "path": "guardrail_ref"}]}, eng)
    check("valid plan passes + gets a limit cap", good["limit"] == ag.LIMIT_CAP and good["select"])
    for bad, why in [
        ({"from": "Secrets"}, "unknown type"),
        ({"from": "Process", "where": [{"op": "drop", "path": "id"}]}, "bad op"),
        ({"from": "Process", "where": [{"op": "predicate", "name": "rm_rf"}]}, "unknown predicate"),
        ({"from": "Process", "select": ["password"]}, "unknown field"),
        ({"from": "Process", "sneaky": 1}, "unknown key"),
    ]:
        try:
            ag.validate_plan(bad, eng); ok = False
        except ag.PlanError:
            ok = True
        check(f"invalid plan rejected: {why}", ok)

    # 8. full LLM path via an injected transport (no key, no network)
    def transport(question, schema):
        return '```json\n{"from":"Task","where":[{"op":"predicate","name":"agent_task"}],' \
               '"select":["id","name"]}\n```'
    la = ag.Agent(llm_transport=transport)
    r = la.ask("show me the robots doing work")  # not a curated intent -> LLM planner
    check("LLM planner answers an open question", r["matched"] and r["planner"] == "llm" and r["n"] == 8)
    check("LLM answer carries a Show-query receipt", "FROM Task" in r["cql"])
    check("LLM answer cites it was model-planned + validated",
          any("LLM planner" in x for x in r["assumptions"]))

    # 9. a malformed model reply falls back honestly (never crashes, never faked)
    bad_agent = ag.Agent(llm_transport=lambda q, s: "sorry I can't help")
    rb = bad_agent.ask("something totally open ended")
    check("malformed LLM reply -> honest fallback, not a fake answer",
          not rb["matched"] and "LLM planner error" in rb["note"])

    # 10. a curated question still uses the deterministic planner even with LLM enabled
    r = la.ask("which processes have no guardrail?")
    check("curated question stays deterministic when LLM is on", r["planner"] == "intent")

    # 11. empty question handled
    check("empty question returns suggestions, no crash", a.ask("")["suggestions"])

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
