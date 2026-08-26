# Governance module — Phase 2

The place a **process owner edits a Guardrail Policy without an engineering ticket**
(Core Model §09 Phase 2). A small stdlib web app over the same object graph and event
log the MCP server reads — so an edit made here is live for agents on their next call,
with no deploy.

## What it delivers (the three Phase-2 items)

1. **Guardrail Policy editable in the UI** — browse processes → open a guardrail → change
   allowed/forbidden actions, `escalate_if`, data scope, rate limit, escalation path, audit
   requirement → **Save new version**. Versioned, never overwritten.
2. **Risk & control linkage live** — the right panel shows the Risk & Control entries the
   open guardrail governs (the `RiskControl.guardrail_ref` link, surfaced).
3. **Audit log finalized to ISO 9001 §7.5** — every edit writes an immutable change-control
   event (reviewer + reason + version); the Audit tab unions those with agent-action events
   into one §7.5 trail. See [`../schema/AUDIT-LOG.md`](../schema/AUDIT-LOG.md).

## Guarantees enforced on every edit

- **Validated** against the locked `guardrail-policy.schema.json` — an invalid edit is refused, not shipped.
- **Linted** — `escalate_if` must parse under the same evaluator the Enforcement Point runs, so a bad condition can't reach agents.
- **Versioned** — `version` bumps; the prior version is retained (event-sourced).
- **Attributed** — reviewer role + reason required (ISO 9001 §7.5); an empty reason is rejected.
- **One source of truth** — committed to `data/edits.log.jsonl`; `continuum_core.Graph` folds it, so the MCP path returns the edited policy immediately.

## Run

```bash
cd continuum-core
python3 -m venv .venv && . .venv/bin/activate
pip install -r mcp_server/requirements.txt        # mcp, tiktoken, jsonschema
python3 governance/app.py                          # http://localhost:8787
```

(An interactive Claude Code session can also launch it from `.claude/launch.json` →
`continuum-governance`.)

## Test the write path (no server, no framework)

```bash
python3 governance/test_store.py    # 14 assertions: version bump, §7.5 trail,
                                     # one-source-of-truth, invalid-edit rejection, audit
```

## Files

```
governance/
├── app.py            # stdlib HTTP server: static UI + JSON API over store.py
├── store.py          # the validated, versioned edit path (the write backbone)
├── test_store.py     # write-path assertions
├── static/           # vanilla-JS three-pane editor (no build step)
│   ├── index.html · styles.css · app.js
└── README.md
```

## Verified end-to-end (this session)

Editing `gr.CO.3.2.7` in the browser (escalate `risk_score > 0.7` → `risk_score > 0.85 or
confidence < 0.6`, with a reason) bumped it to **v4**, wrote the change-control event, and
an agent reading over the MCP core immediately saw v4 and the new low-confidence trigger.
A malformed `escalate_if` was refused with an error and left the version at v4. Reset the
demo state by deleting `data/edits.log.jsonl`.
