# Advisor — analyze anything against best practices & standards

An in-app AI window (D17). Point it at a **process, guardrail, task, the whole model**,
or **pasted content / data**, and it returns a scored analysis — each finding citing the
standard it comes from and giving a recommendation.

## Standards it checks against

- **ISO 9001** — §4.4 (process approach: owner, typed I/O, monitoring, interfaces),
  §7.5 (documented information), §7.5.3 (retention & disposition).
- **ISO 9004** — maturity / PDCA.
- **APQC PCF** — classification & join key.
- **Continuum doctrine** — §04 (enforcement, least privilege, escalation to a role),
  §11 (guardrails permissive-but-scoped; no high-stakes action allowed unattended;
  explicit deny-list), §12 (traceability completeness & reviewed-guardrail coverage).

## What each subject gets

| Subject | Sample checks |
|---|---|
| **Process** | single owner · typed inputs/outputs · monitored by a KPI · traces to an objective · governed by a guardrail · maturity score · risk linked |
| **Guardrail** | non-empty allow-list · **no high-stakes action allowed unattended** · explicit deny-list · valid escalation condition · least-privilege data scope · escalation to a role · reviewed vs. bare default |
| **Task** | data scope declared · has a performer · **agent step is guarded (fail-closed)** |
| **Content** (text) | heuristic ISO 9001 §7.5 doc-control checklist: purpose, owner, version, review, inputs/outputs, escalation, retention |
| **Data** (JSON) | validated against the locked entity schema when the id is recognized |
| **Whole model** | no broken refs · full traceability · guardrail coverage · avg process-design health, with the lowest-scoring processes |

Each result is a **scorecard** (%) plus findings ranked by severity, rendered as an
assistant turn in the window.

## The AI seam (honest)

The engine is the **`RulesAdvisor`** — deterministic, needs no model access, works today, and
**the score is always rule-based**. A deeper natural-language review (nuance a rule set can't
reach — *is this guardrail's wording faithful to its intent? is this SOP actually clear?*) is
the **`LLMAdvisor`**, wired behind the shared env var (see below). With no key it **refuses**
(like the signal connectors and the ask agent's planner) and the `RulesAdvisor` stands in.

## Enabling the AI reviewer

```bash
export CONTINUUM_LLM_API_KEY=sk-...      # or ANTHROPIC_API_KEY
export CONTINUUM_LLM_MODEL=claude-...    # optional; defaults to claude-opus-4-8
python3 advisor/app.py
```

The **`Advisor`** orchestrator always computes the deterministic scorecard first, then — if a
key is present — asks the `LLMAdvisor` to **augment** it. The model is given the subject and the
rule checks and returns *only* qualitative findings the rules can't capture; those are
normalized (severity whitelisted, text length-capped, count-capped) and shown in a distinct
**AI reviewer** block marked *advisory*. Two honest guarantees: the LLM findings **never change
the rule-based score**, and they never drive an action — they are narrative for a human. A model
error or malformed reply is surfaced as an `AI reviewer error` and the deterministic result
stands unchanged. The shared model plumbing (env var, call, JSON extraction) lives in
[`mcp_server/llm.py`](../mcp_server/llm.py), the same helper the ask agent uses.

## Run

```bash
python3 advisor/app.py            # http://localhost:8790 (alongside :8787 / :8788 / :8789 / :8791)
python3 advisor/test_advisor.py   # 26 asserts
```

## Files

- `advisor.py` — `RulesAdvisor` (rule engine) + `LLMAdvisor` (env-gated reviewer) + `Advisor` (orchestrator).
- `app.py` — stdlib server: `GET /api/subjects` + `POST /api/analyze` + the static window.
- `static/` — vanilla-JS chat-style advisor window (theme-aware) with the AI-reviewer block.
- `test_advisor.py` — engine + LLM-augmentation assertions across every subject type.
