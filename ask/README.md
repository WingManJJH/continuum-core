# Ask the Agent — a plain-English question over the model

An in-app window (D18), modeled on a text-to-SQL "ask the data" agent but for the
Continuum **graph**. You ask a question; the agent writes a **read-only** graph
query, runs it against the one graph, and answers with a table, the assumptions it
made, and the exact query it ran (**Show query**).

## Two honest layers

Mirrors the advisor's `RulesAdvisor` / `LLMAdvisor` split:

- **`QueryEngine`** — a real, read-only executor over the graph. It only reads
  (`graph.all` / `graph.get` / `effective_guardrail`); it never appends an event
  or edits an entity. This is what actually runs today.
- **Planner** — turns a question into a query plan. The deterministic
  **`IntentPlanner`** (keyword intents over a curated question set) stands in and
  works with no model access. The **`LLMPlanner`** is the declared seam where a
  live model generalizes to *arbitrary* questions once auth (API / OAuth) is
  provisioned; until then it **refuses**, exactly like the signal connectors, the
  pilot agent, and the advisor's `LLMAdvisor`.

So an open-ended question isn't faked — the window says it needs the LLM planner
and points you at the questions the deterministic planner can answer today.

## Questions it answers today

| Question | What it checks |
|---|---|
| Which processes have no guardrail? | ungoverned processes (§04/§11) |
| Which guardrails are unreviewed defaults? | stamped defaults awaiting QMS sign-off (§12) |
| Which processes do not trace to a strategic objective? | broken golden thread (§12) — finds the planted `HR.7.2.5` |
| Which tasks have an agent bound? | every agent-in-the-loop step |
| Which agent steps rely on an inherited guardrail? | agent tasks with no task-specific guardrail |
| Which KPIs are off target? | breach by KPI direction (lower/higher is better) |
| Which processes have the lowest maturity? | bottom-5 by maturity score (ISO 9004) |
| Which guardrails allow a high-stakes action? | allow-list vs the high-stakes set (§11) |
| Which APQC domains does the model cover? | domain span |
| show / tell me about `<id>` | full stored record for any entity id |

Every answer carries a **Show query** receipt — the read-only query the agent ran,
rendered in a small SQL-like form (`FROM … FOLLOW … WHERE … SELECT …`), so the
answer is auditable the same way "Show SQL" makes a text-to-SQL answer auditable.

## Run

```bash
python3 ask/app.py            # http://localhost:8791 (alongside :8787 / :8788 / :8789 / :8790)
python3 ask/test_agent.py     # 23 asserts
```

## Files

- `agent.py` — `QueryEngine` (read-only executor) + `render_cql` + the `Intent`
  registry + `Agent.ask()`; `LLMPlanner` (auth-gated seam).
- `app.py` — stdlib server: `GET /api/examples` + `POST /api/ask` + the static window.
- `static/` — vanilla-JS chat-style window (theme-aware), with Show query + suggestion chips.
- `test_agent.py` — engine + planner + seam assertions.
