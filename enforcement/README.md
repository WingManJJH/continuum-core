# Enforcement Point — Phase 3

The generic gate every agent action passes through (Core Model §04 Figure 3, §11).
Makes the guardrail a **gate the action passes through**, not advice an agent may read.

## The invariant

`EnforcementPoint.act(task_id, action, actor, facts)` is the **only** way the pilot
agent can affect the world — it holds the tool callables; the agent does not. On each call:

| Guardrail decision | What the EP does |
|---|---|
| **allow** | run the underlying tool, then log `success` |
| **escalate** | do **not** run the tool; enqueue for the human role, log `escalated` |
| **deny** (forbidden / not-allowed / out-of-scope) | do **not** run the tool; log `denied` |
| over **rate_limit** | deny before any policy work; log `rate_limited` |

The tool runs **only** on `allow`. This is §11's "the MCP server is the only sanctioned
path" turned into code, not a diagram. Rate limiting is now stateful (sliding window per
agent per guardrail) — the Phase-1 "not enforced in the stateless prototype" note is closed.

The EP holds **no policy**: it reads the guardrail via `continuum_core` and obeys it, so a
governance edit (Phase 2) changes enforcement with no code change.

## Run

```bash
python3 enforcement/pilot_agent.py     # a pilot agent, every action routed through the EP
python3 enforcement/test_enforce.py    # 13 assertions incl. the tool-runs-only-on-allow invariant
```

## Files

- `enforce.py` — the `EnforcementPoint`: decision → execute/escalate/deny, rate limiting, escalation queue.
- `pilot_agent.py` — a minimal, framework-agnostic agent wired to the EP (a real MCP/Claude agent drops in unchanged).
- `test_enforce.py` — invariant + branch + rate-limit + audit assertions.

Every outcome writes to `data/events.log.jsonl` — the same log the Conformance Check (§06) reads.
Escalations queue to `data/escalations.jsonl` (runtime state, git-ignored).
