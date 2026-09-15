# Continuum Core — Phases 1–4

This directory executes the **Immediate next steps** in §13 of *The Continuum Core Model*
(`../Continuum Core Model.rtf`), the follow-on decisions ratified in [`DECISIONS.md`](DECISIONS.md),
and the four-phase roadmap of §09 (Phase 2 governance, Phase 3 signal & agent, Phase 4 enterprise
connection). Each item is a concrete, runnable deliverable.

> **New here?** [`MANUAL.md`](MANUAL.md) is the step-by-step guide to setting up, running, and
> testing everything below — start there.

> **Related:** [`DECISIONS.md`](DECISIONS.md) records the rationale (D1–D21). The build's
> working notes live in the maintainer's private `continuum-memory` repo — internal, not
> publicly accessible.

> **Environment note:** every live enterprise connector (Notion, Teams, Slack, Outlook, Gmail) and
> the pilot agent LLM require OAuth/network that this build does not have. Wherever that bites, the
> capability is declared with its real interface and **stubbed with a clear error**, and a file
> connector / fixtures stand in so the engine is exercised for real. These edges are called out
> inline, in [`DECISIONS.md`](DECISIONS.md), and in each module README — never silently faked.

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

**Phase 3 — Signal & agent infrastructure (§09):**

| Phase-3 item | Deliverable | Where |
|---|---|---|
| MCP server ships (get_task_context / check_guardrail / log_action) | shipped in Phase 1, now fronted by the Enforcement Point | [`mcp_server/server.py`](mcp_server/server.py) |
| Enforcement Point built + wired to one pilot agent | real gate (execute only on allow; escalate/deny; rate limit) + pilot agent | [`enforcement/`](enforcement/README.md) |
| Signal Layer (Notion/Outlook first) feeds Conformance Check (§06) | connector interface (+ file stand-in; live connectors need OAuth) + drift engine | [`signal/`](signal/README.md) |

**Phase 4 — Continuous enterprise connection (§09):**

| Phase-4 item | Deliverable | Where |
|---|---|---|
| Full guardrail enforcement across all agent-bound tasks | enforcement sweep over all 8 bindings (fail-closed) + §12 coverage | [`enforcement/sweep.py`](enforcement/sweep.py) |
| Teams/Slack/Gmail signal (sequenced by sensitivity) | OAuth-gated connectors + enable-order (auth unavailable → file stand-in) | [`signal/connectors.py`](signal/connectors.py) |
| Strategy-to-execution rollup dashboard as a standing report (§05) | rollup engine + web dashboard + §12 metric tiles | [`dashboard/`](dashboard/README.md) |

## Quick start

```bash
cd continuum-core
python3 -m venv .venv && . .venv/bin/activate
pip install -r mcp_server/requirements.txt        # mcp, tiktoken, jsonschema

# Start all five web apps at once (Ctrl-C stops them all)
python3 run.py                                    # governance :8787 · dashboard :8788 · canvas :8789 · advisor :8790 · ask :8791
python3 run.py --only ask,advisor                 # or a subset · --list to list · set CONTINUUM_LLM_API_KEY for live LLM

# Phase 1 — harness
python3 mcp_server/token_budget.py --validate   # schema-validate seed + §08 budgets + whole-graph worst case
python3 mcp_server/traceability.py              # §01/§12 lint: orphan KPIs, un-parented processes, broken refs
python3 mcp_server/scenario.py                  # walk an agent through the MCP tool loop

# Phase 2 — governance module (editable guardrails)
python3 governance/test_store.py                # guardrail write-path assertions (versioning, §7.5, one-source-of-truth)
python3 governance/test_taskedit.py             # 16 asserts: Task write path — add/rename/reorder/remove a step
python3 governance/test_authoring.py            # 18 asserts: author a process (auto default guardrail) + drag-insert steps
python3 governance/test_binding.py              # 13 asserts: bind/unbind an agent to a step from the canvas
python3 governance/app.py                       # http://localhost:8787 — the editor UI

# Phase 3 — signal & agent infrastructure
python3 enforcement/pilot_agent.py              # pilot agent; every action routed through the Enforcement Point
python3 enforcement/test_enforce.py             # 13 asserts: tool runs only on allow; escalate/deny; rate limit
python3 signal/conformance.py                   # §06 Conformance Check: model vs. reality (drift report)
python3 signal/test_conformance.py              # 8 asserts incl. "conformance never mutates the model"

# Phase 4 — continuous enterprise connection
python3 enforcement/sweep.py --keep             # full enforcement across all 8 agent-bound tasks (+ populates the log)
python3 dashboard/app.py                         # http://localhost:8788 — the §05 standing report
python3 dashboard/test_rollup.py                 # 13 asserts: top-down / bottom-up / coverage / metrics

# Audit-log tamper-evidence (ISO 9001 §7.5 hardening)
python3 audit/test_audit_chain.py                 # 13 asserts: content/delete/reorder/truncate/whole-log/reset
python3 audit/test_anchor.py                       # 10 asserts: off-box anchor catches log+heads co-forgery
python3 audit/verify.py                            # re-walk chain + off-box anchor (exit 1 on tampering)
python3 governance/test_retention.py               # 16 asserts: §7.5.3 schedule, legal holds, chain-safe disposition
python3 governance/retention.py                    # retention plan (add --apply to archive + ledger due records)

# Process canvas — interactive §03 Canvas View
python3 maps/test_mapdata.py                       # 12 asserts: flow / agent step / escalation / override / editor payload
python3 maps/app.py                                # http://localhost:8789 — 3-pane canvas: flowchart/RACI/checklist + in-canvas guardrail editing

# Advisor — analyze anything vs best practices & standards
python3 advisor/test_advisor.py                    # 26 asserts: rules + LLM-augmentation across every subject
python3 advisor/app.py                             # http://localhost:8790 — AI window: score a subject against ISO 9001/9004/APQC + Core Model doctrine

# Ask the Agent — plain-English question -> read-only graph query -> answer
python3 ask/test_agent.py                          # 35 asserts: NL intents, read-only receipt, plan validation, LLM-planner wiring
python3 ask/app.py                                 # http://localhost:8791 — ask window: writes a read-only query, runs it, Show query
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

**Tamper-evidence (built, D9):** every audit event is hash-chained (`prev_hash`/`hash`); a
per-log heads anchor catches truncation. `python3 audit/verify.py` re-walks the chain and the
governance **Audit** tab shows a live *chain intact / tampering detected* badge — any edit,
deletion, reorder, or truncation is caught (see [`schema/AUDIT-LOG.md`](schema/AUDIT-LOG.md)).
**Off-box anchor (built, D10):** `audit/anchor.py` HMAC-signs a `combined_head` fingerprint over
both logs and publishes it to a notary the writer can't rewrite; `verify_against_anchor()` catches the
log+heads co-forgery the chain alone can't (proven in `audit/test_anchor.py`). **Still flagged:**
hosting the key + notary off-box is a deployment step (`ExternalNotary` is auth-gated), and a
retention-policy engine remains a named next step.

## What Phase 3 proves (signal & agent infrastructure)

**The guardrail is a gate, not advice.** The [Enforcement Point](enforcement/README.md) runs the
underlying tool **only** on an `allow` decision — `escalate` queues for a human and runs nothing,
`deny` blocks, and stateful rate limiting caps a looping agent. A pilot agent, whose only path to
acting is `ep.act(...)`, demonstrated all branches; a test asserts the tool ran exactly on the allows
(13 assertions). This is §11's "only sanctioned path" enforced in code, and it closes the Phase-1
"rate limiting not enforced" note.

**The model stays honest against reality.** The [Conformance Check](signal/README.md) (§06) compares
the documented model with the agent execution log and external signals, surfacing five drift types —
including an agent running against a **stale guardrail** (the §06 early-warning). Per §06 it only
*surfaces*: every finding needs human review and the Check never writes to the model (asserted).

**Honest edge:** live Notion/Outlook connectors need OAuth (unavailable in this build) — they're
declared with their scopes and raise a clear error, while a file connector stands in so the drift
engine is exercised for real. Swap them in once authorized; the interface is unchanged.

Run: `python3 enforcement/pilot_agent.py && python3 signal/conformance.py`.

## What Phase 4 proves (continuous enterprise connection)

**Enforcement is universal, not a pilot.** [`enforcement/sweep.py`](enforcement/sweep.py) drives the
Enforcement Point across **all 8 agent-bound tasks** — every one gated (execute / escalate / deny) —
and reports §12 guardrail coverage. Fail-closed: a task with no effective guardrail is a defect, not
a silent allow.

**Strategy traces to the agent action, and back — as a standing report.** The
[dashboard](dashboard/README.md) (§05) walks objective → KPI (live vs target) → process →
agent-bound task → what the agent did, and rolls agent activity back up to the objective. Verified
live in the browser. The §12 metric tiles are computed where derivable — **guardrail coverage 12%
(1/8 reviewed — honest: only the signed-off KYC guardrail; the rest run under defaults)**,
traceability 88%, agent-activity counts — and the two that need human disposition data (escalation
precision, drift-to-update latency) are shown as **`needs data`, not fabricated**.

**Honest edge:** the live Teams/Slack/Gmail (and Notion/Outlook) connectors need OAuth, unavailable
here. They're declared with scopes and a sensitivity enable-order (`SENSITIVITY_ORDER`) and raise a
clear error; the file connector stands in. This is the real-data half of Phase 4 — gated on
connector auth, buildable the moment it's granted, with no downstream change.

Run: `python3 enforcement/sweep.py --keep && python3 dashboard/app.py`.

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
│   ├── events.log.jsonl        # (runtime) agent-action events, hash-chained — git-ignored
│   ├── edits.log.jsonl         # (runtime) governance change-control events, hash-chained — git-ignored
│   └── audit_heads.json        # (runtime) per-log chain head + count — git-ignored
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
│   ├── retention.py            #   §7.5.3 retention scheduler + chain-safe disposition (D12)
│   ├── test_store.py           #   guardrail write-path assertions
│   ├── test_taskedit.py        #   16 asserts: Task write path (add/rename/reorder/remove)
│   ├── test_authoring.py       #   18 asserts: Process write path + positional insert
│   ├── test_binding.py         #   13 asserts: AgentBinding write path (bind/unbind)
│   ├── test_retention.py       #   16 asserts: schedule / holds / disposition
│   ├── static/                 #   vanilla-JS three-pane editor (index.html/styles.css/app.js)
│   └── README.md
├── enforcement/                # Phase 3 gate + Phase 4 full-coverage sweep
│   ├── enforce.py              #   execute-only-on-allow, escalate/deny, rate limiting
│   ├── pilot_agent.py          #   a pilot agent that can only act through the EP
│   ├── sweep.py                #   Phase 4 — EP across ALL agent-bound tasks (fail-closed)
│   ├── test_enforce.py         #   invariant + branch + rate-limit assertions
│   └── README.md
├── signal/                     # Phase 3 Conformance + Phase 4 connectors (§06)
│   ├── connectors.py           #   SignalConnector + FileConnector + Notion/Outlook/Teams/Slack/Gmail OAuth stubs
│   ├── conformance.py          #   drift engine: model vs. reality, human-review-only
│   ├── signals.sample.jsonl    #   fixture external activity
│   ├── agent_events.sample.jsonl # fixture agent-log events
│   ├── test_conformance.py     #   drift-detection + non-mutation assertions
│   └── README.md
├── dashboard/                  # Phase 4 — §05 strategy→execution standing report
│   ├── rollup.py               #   engine: top-down / bottom-up / coverage / §12 metrics
│   ├── app.py                  #   stdlib HTTP server: /api/rollup + static dashboard
│   ├── static/                 #   vanilla-JS leadership view
│   ├── test_rollup.py          #   rollup / coverage / metrics assertions
│   └── README.md
├── audit/                      # ISO 9001 §7.5 tamper-evidence (hash chain D9 + off-box anchor D10)
│   ├── verify.py               #   re-walk the chain + off-box anchor; CLI + JSON report
│   ├── anchor.py               #   HMAC-signed off-box anchor over both logs (co-forgery defense)
│   ├── test_audit_chain.py     #   13 asserts: tamper modes + reset hygiene
│   └── test_anchor.py          #   10 asserts: anchor catches consistent co-forgery
├── advisor/                    # AI advisor window — analyze vs best practices & standards (D17)
│   ├── advisor.py              #   RulesAdvisor engine + LLMAdvisor (auth-gated seam)
│   ├── app.py                  #   stdlib server: /api/subjects + /api/analyze + chat window
│   ├── static/                 #   vanilla-JS agent window
│   └── test_advisor.py         #   18 asserts across every subject type
├── maps/                       # §03 Canvas View — interactive process canvas (D11 + D13)
│   ├── mapdata.py              #   per-process map data incl. the editable guardrail
│   ├── app.py                  #   stdlib server: /api/maps + PUT /api/guardrail + POST /api/task (reuses governance store)
│   ├── static/                 #   3-pane canvas: view + edit guardrails/structure + author processes + bind agents
│   └── test_mapdata.py         #   12 asserts: flow / agent step / escalation / override / editor payload
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

## License

[MIT](LICENSE) © 2026 Jeffrey Hunt.
