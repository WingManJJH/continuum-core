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

The engine is the **`RulesAdvisor`** — deterministic, needs no model access, works today.
A deeper natural-language review (nuance a rule set can't reach — *is this guardrail's
wording faithful to its intent? is this SOP actually clear?*) is the **`LLMAdvisor`**: it
requires model access (API / OAuth), is **declared and refuses** until that's provisioned
(exactly like the signal connectors and the pilot agent), and the `RulesAdvisor` stands in.

## Run

```bash
python3 advisor/app.py            # http://localhost:8790 (alongside :8787 / :8788 / :8789)
python3 advisor/test_advisor.py   # 18 asserts
```

## Files

- `advisor.py` — `RulesAdvisor` (the analysis engine) + `LLMAdvisor` (auth-gated seam).
- `app.py` — stdlib server: `GET /api/subjects` + `POST /api/analyze` + the static window.
- `static/` — vanilla-JS chat-style advisor window (theme-aware).
- `test_advisor.py` — engine assertions across every subject type.
