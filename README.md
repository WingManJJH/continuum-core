# Continuum Core — Phases 1 & 2

This directory executes the **Immediate next steps** in §13 of *The Continuum Core Model*
(`../Continuum Core Model.rtf`), the follow-on decisions ratified in [`DECISIONS.md`](DECISIONS.md),
and the **Phase-2 governance module** (§09). Each item is a concrete, runnable deliverable.

**Phase 1 — Foundation (§13):**

| # | §13 step | Deliverable | Where |
|---|---|---|---|
| 1 | Lock the Process / Guardrail / Task schemas as the literal Phase-1 data model | 8 entity schemas + event envelope + lock doc | [`schema/`](schema/) · [`schema/SCHEMA.md`](schema/SCHEMA.md) |
| 2 | Prototype the MCP server's 3 core tools; validate §08 token budgets against a real agent | MCP server + core engine + hand-built 8-domain graph + token harness + traceability linter + end-to-end scenario | [`mcp_server/`](mcp_server/) · [`data/seed.json`](data/seed.json) |
| 3 | Draft the default Guardrail Policy template (permissive-but-scoped, §11), reviewed vs. ISO 9001 | Default policy (signed off) + ISO-annotated template | [`guardrail-template/`](guardrail-template/) |
| 4 | Fold into design-partner conversations; test the "editable guardrail" framing | Validation guide + ready-to-fill call log | [`design-partner/`](design-partner/) |

**Phase 2 — Governance & maturity (§09):**

| Phase-2 item | Deliverable | Where |
|---|---|---|
| Guardrail Policy editable in the UI (versioned, no deploy) | Governance web app + event-sourced edit layer + write-path tests | [`governance/`](governance/README.md) |
| Risk / control linkage live | Linked Risk & Control panel in the editor | [`governance/`](governance/) |
| Audit log finalized against ISO 9001 §7.5 | Change-control + agent-action trail; §7.5 requirement→mechanism map | [`schema/AUDIT-LOG.md`](schema/AUDIT-LOG.md) |

## Quick start

```bash
cd continuum-core
python3 -m venv .venv && . .venv/bin/activate
pip install -r mcp_server/requirements.txt        # mcp, tiktoken, jsonschema

# Phase 1 — harness
python3 mcp_server/token_budget.py --validate   # schema-validate seed + §08 budgets + whole-graph worst case
python3 mcp_server/traceability.py              # §01/§12 lint: orphan KPIs, un-parented processes, broken refs
python3 mcp_server/scenario.py                  # walk an agent through the MCP tool loop

# Phase 2 — governance module (editable guardrails)
python3 governance/test_store.py                # write-path assertions (versioning, §7.5 trail, one-source-of-truth)
python3 governance/app.py                       # http://localhost:8787 — the editor UI
```

The **core engine** (`continuum_core.py`) needs only the standard library; `mcp`,
`tiktoken`, and `jsonschema` are for the server, harness, and governance app.

Run the MCP server itself (stdio) and register it with a client:

```bash
python3 mcp_server/server.py
# claude mcp add continuum -- python3 /abs/path/to/continuum-core/mcp_server/server.py
```

## What the prototype proves

Built before any UI exists (§13) and now stress-tested across an **8-domain graph**
(CO, FN, SC, MS, IT, PD, HR, SV — 8 processes, 25 tasks, 10 KPIs, 9 guardrails).

**All four §08 budgets pass, measured on the wire and swept across the whole graph**
(tiktoken `o200k_base`; `cl100k_base` cross-checked):

| Payload | KYC example | Whole-graph worst case | Budget |
|---|---|---|---|
| Single task context | 136 | 147 (`SC.4.3.6.t3`) | < 200 *(raised from 150 — D1)* |
| Guardrail check response | 16–30 | 30 | < 40 |
| Process summary (task list) | 145 | 145 (`CO.3.2.7`) | < 400 |
| Strategy rollup (obj → KPI) | 63 | 63 | < 250 |

**The five guardrail decision branches** — all verified in `scenario.py`:
`allow` · `escalate` · `deny: action_forbidden` · `deny: action_not_allowed` ·
`deny: out_of_scope`. Every logged action cites the version-pinned guardrail ref it
acted under, appended immutably to `data/events.log.jsonl` (§04).

**Guardrail inheritance & override** — `IT.8.4.2.t3` carries a task-level override
(`gr.IT.8.4.2.ADMIN`) stricter than its process policy. The *same* action,
`grant_standard_access`, resolves to **allow** on `t2` (inherits the process policy)
and **deny** on `t3` (the override forbids it) — the §02 inheritance rule, demonstrated.

**Traceability / data quality (§01, §12)** — `traceability.py` flags the deliberately
planted defects: two orphan KPIs (`kpi.unused_metric`, `kpi.applicant_pass_rate`) and one
process with no strategic parent (`HR.7.2.5`), and reports a **§12 completeness score of
88%** (7 of 8 active processes fully traced to strategy). A dangling process is a flagged
defect, not a normal state.

### Resolved findings (from validating with a real tokenizer)

Both open findings from the first prototype are now decided — see [`DECISIONS.md`](DECISIONS.md):

1. **D1** — the §03 "~70 token" annotation was ~2× optimistic (real ~136; graph worst case 147).
   Budget raised to **200** and the guardrail kept inline, rather than split behind a second call.
2. **D2** — compression is **8–15× for a full-process export; ~3× per task**, not 8–15× per task.
   Restated in the harness output and here; still to fold into the spec's §03 prose.

Reproduce: `python3 token_budget.py --validate && python3 traceability.py`.

## What Phase 2 proves (governance module)

The whole architecture bets on "guardrails are data, not code — editable by a process
owner without a deploy" (§01/§04). Phase 2 makes that real and **verified it end-to-end in
a running app**:

- A process owner edited `gr.CO.3.2.7` in the browser (`escalate_if 0.7` → `0.85 or
  confidence < 0.6`, with a reason) → **v3 bumped to v4**, no code, no deploy.
- A fresh MCP-side `Graph` **immediately returned v4** and the new low-confidence trigger
  fired — one source of truth (`governance/test_store.py` asserts this; also checked live).
- A malformed `escalate_if` was **refused** with an error and left the version untouched —
  the governance-time lint stops a bad condition reaching agents.
- Every edit wrote an immutable change-control event; the Audit tab unions those with
  agent-action events into the ISO 9001 §7.5 trail ([`schema/AUDIT-LOG.md`](schema/AUDIT-LOG.md)).

Run it: `python3 governance/app.py` → http://localhost:8787. Details in
[`governance/README.md`](governance/README.md). This UI is also the higher-fidelity
design-partner demo from [`design-partner/validation-guide.md`](design-partner/validation-guide.md) §5.

**Honest edges (flagged, deferred to Phase 3+):** audit-log tamper-evidence (hash chain),
a retention-policy engine, and consolidating the two logs into one signed store. The §7.5
*content* requirements are met; the tamper-evidence *hardening* is named, not assumed.

## Layout

```
continuum-core/
├── DECISIONS.md                # ratified decisions on top of the spec (D1–D6)
├── schema/                     # Deliverable 1 — LOCKED Phase-1 data model
│   ├── SCHEMA.md               #   lock doc: IDs, inheritance, ISO/APQC provenance
│   ├── AUDIT-LOG.md            #   Phase 2 — audit trail finalized to ISO 9001 §7.5
│   ├── _envelope.event.schema.json
│   └── <8 entity>.schema.json
├── data/
│   ├── seed.json               # hand-built 8-domain graph (reproduces the §03 KYC example)
│   ├── events.log.jsonl        # (runtime) agent-action events — git-ignored
│   └── edits.log.jsonl         # (runtime) governance change-control events — git-ignored
├── mcp_server/                 # Deliverable 2
│   ├── continuum_core.py       #   framework-independent engine (stdlib) + event-sourced fold/append
│   ├── server.py               #   MCP server: get_task_context / check_guardrail / log_action
│   ├── token_budget.py         #   §08 validation + schema validation + whole-graph sweep
│   ├── traceability.py         #   §01/§12 data-quality linter
│   ├── scenario.py             #   end-to-end agent loop, tokens on the wire
│   └── requirements.txt
├── governance/                 # Phase 2 — the editable-guardrail module
│   ├── app.py                  #   stdlib HTTP server: static UI + JSON API
│   ├── store.py                #   validated, versioned edit path (write backbone)
│   ├── test_store.py           #   write-path assertions
│   ├── static/                 #   vanilla-JS three-pane editor (index.html/styles.css/app.js)
│   └── README.md
├── guardrail-template/         # Deliverable 3 (signed off)
│   ├── default-guardrail-policy.json
│   └── DEFAULT-GUARDRAIL-TEMPLATE.md
└── design-partner/             # Deliverable 4
    ├── validation-guide.md
    └── call-log.md             #   ready-to-fill tracker for the next 3 calls
```

## Boundaries held from the spec

- Execution backend decision unchanged: build independently or on a permissive engine
  (e.g. Temporal); never an unlicensed Zeebe embed (§07).
- The MCP server is the **only** sanctioned path to agent-actionable systems for a
  guardrailed task — a policy commitment, not just this diagram (§11 bypass risk).
- Canvas decorative properties (position, color, label placement) are kept entirely out
  of both the schemas and the agent payloads (§08).
