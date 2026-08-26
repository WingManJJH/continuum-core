# Design-Partner Call Log — "editable guardrail" test

Instrument for [validation-guide.md](validation-guide.md). Run on the **next 3**
pricing/ICP calls (§13 step 4 / DECISIONS.md D5). Fill one row per call in the
last ~12 minutes. The three columns below **are** the deliverable back to the team —
a decision, not a transcript.

> Note: placing the calls is a human action — this file is the ready-to-fill log.
> Fill `Spontaneous frame`, `A/B winner`, and `Verdict` for each; the rollup at the
> bottom turns 3 rows into a go/no-go read.

## The three columns (definitions)

- **Spontaneous frame** — the *exact nouns* the owner used, unprompted (Move 1), for
  "what the AI is allowed to do" (e.g. "permissions", "approvals", "controls", "guardrails",
  "what it can touch"). This is the Fail-B evidence and doubles as positioning research.
- **A/B winner** — which framing they'd forward to their boss (Move 3): **F1** "guardrails
  your process owners can edit without an engineering ticket" · **F2** "you set the
  boundaries for what the AI can do — change them yourself, instantly, without IT" ·
  **F3** "every automated step has an approval policy you own".
- **Verdict** — **Supported** (wants to hold the control) · **Fail-A** (wants eng/IT to own
  it, or reads self-edit as burden/risk) · **Fail-B** (wants it, but a non-F1 frame won).

## Log

| # | Date | Company / ICP | Owner role on call | Spontaneous frame (their words) | A/B winner | Bypass Q asked? | Verdict | Notes |
|---|------|---------------|--------------------|---------------------------------|-----------|-----------------|---------|-------|
| 1 |      |               |                    |                                 | F_ |  Y / N | Supported / Fail-A / Fail-B |  |
| 2 |      |               |                    |                                 | F_ |  Y / N | Supported / Fail-A / Fail-B |  |
| 3 |      |               |                    |                                 | F_ |  Y / N | Supported / Fail-A / Fail-B |  |

## Rollup (fill after call 3)

- **Verdict tally:** Supported __ / 3 · Fail-A __ / 3 · Fail-B __ / 3
- **A/B winner tally:** F1 __ · F2 __ · F3 __
- **Bypass question raised unprompted:** __ / 3  → if ≥2, bypass-prevention (§11) goes in the pitch, not the appendix.
- **Read:**
  - ≥2 **Supported** → hypothesis holds; build the Phase-2 governance UI on this promise. If a non-F1 frame won the A/B, adopt that frame's wording.
  - ≥2 **Fail-A** → **stop** and revisit who the guardrail editor is *for* before Phase-2 spends UI budget (the kill gate in validation-guide.md §6).
  - Mostly **Fail-B** → keep the feature, switch to the winning frame, and re-test the new words on the following 2 calls.
- **Vocabulary harvested for pricing/ICP messaging:** _(list the recurring nouns owners used)_

## Demo used

Live prototype (validation-guide.md §5): `python3 mcp_server/scenario.py`, then the
`escalate_if 0.7 → 0.95` edit in `data/seed.json` re-run to flip step 3 escalate→allow,
version-stamped, no deploy.
