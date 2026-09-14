# Continuum Core — User & Test Manual

How to set up, run, and test the Continuum prototype (Phases 1–4). Every command
below is run from the `continuum-core/` directory unless stated otherwise.

- **What each phase is** and how to see it work → [Using it, phase by phase](#using-it-phase-by-phase)
- **Just prove it all works** → [Run every test](#run-every-test)
- **The two web apps** (governance editor, dashboard) → [Web apps](#web-apps)
- **Reset to a clean state** → [Data & reset](#data--reset)
- **What needs OAuth / is stubbed** → [Known limits](#known-limits)
- **Something's wrong** → [Troubleshooting](#troubleshooting)

---

## Prerequisites

- **Python 3.10+** (developed on 3.14). The core engine uses only the standard library.
- No network is needed for anything in this manual. Live enterprise connectors and the
  pilot-agent LLM would need OAuth/network — see [Known limits](#known-limits) — but every
  such path is stubbed with a stand-in so nothing here requires them.

## One-time setup

```bash
cd continuum-core
python3 -m venv .venv
. .venv/bin/activate                 # Windows: .venv\Scripts\activate
pip install -r mcp_server/requirements.txt      # mcp, tiktoken, jsonschema
```

Everything below assumes the venv is active (`. .venv/bin/activate`). If you'd rather not
activate it, prefix commands with `.venv/bin/python` instead of `python3`.

---

## Run every test

The fastest way to confirm the whole system is healthy. From `continuum-core/`:

```bash
python3 mcp_server/token_budget.py --validate \
  && python3 mcp_server/traceability.py \
  && python3 mcp_server/scenario.py \
  && python3 governance/test_store.py \
  && python3 enforcement/test_enforce.py \
  && python3 signal/test_conformance.py \
  && python3 dashboard/test_rollup.py \
  && python3 audit/test_audit_chain.py \
  && python3 audit/test_anchor.py \
  && python3 governance/test_retention.py \
  && python3 governance/test_taskedit.py \
  && python3 governance/test_authoring.py \
  && python3 governance/test_binding.py \
  && python3 maps/test_mapdata.py \
  && python3 advisor/test_advisor.py \
  && python3 ask/test_agent.py \
  && echo "ALL GREEN"
```

Expected: the chain ends with `ALL GREEN`. Per-suite expectations:

| Command | Expect |
|---|---|
| `mcp_server/token_budget.py --validate` | `SCHEMA VALIDATION: ALL VALID`, `RESULT: ALL BUDGETS PASS`, `WORST-CASE SWEEP: ALL UNDER BUDGET` |
| `mcp_server/traceability.py` | `0 error(s), 3 warning(s)` · completeness `88%` (the 3 warnings are **planted on purpose**) |
| `mcp_server/scenario.py` | `RESULT: loop fits the budget on the wire` |
| `governance/test_store.py` | `14 passed, 0 failed` |
| `enforcement/test_enforce.py` | `13 passed, 0 failed` |
| `signal/test_conformance.py` | `8 passed, 0 failed` |
| `dashboard/test_rollup.py` | `13 passed, 0 failed` |
| `audit/test_audit_chain.py` | `13 passed, 0 failed` |
| `audit/test_anchor.py` | `10 passed, 0 failed` |
| `governance/test_retention.py` | `16 passed, 0 failed` |
| `governance/test_taskedit.py` | `16 passed, 0 failed` |
| `governance/test_authoring.py` | `18 passed, 0 failed` |
| `governance/test_binding.py` | `13 passed, 0 failed` |
| `maps/test_mapdata.py` | `12 passed, 0 failed` |
| `advisor/test_advisor.py` | `18 passed, 0 failed` |
| `ask/test_agent.py` | `23 passed, 0 failed` |

187 assertions + 3 harness checks. All suites exit `0` on success. (`traceability.py` exits `1`
**only** if it finds a hard broken reference — never for the expected 3 warnings.)

---

## Using it, phase by phase

### Phase 1 — the model, the MCP tools, the token budgets

**What it is:** the locked 8-entity data model, a hand-built 8-domain graph, and the three
agent-facing MCP tools, with §08 token budgets validated by a real tokenizer.

```bash
# see the four agent payloads (task context / guardrail check / process summary / rollup)
python3 mcp_server/continuum_core.py

# validate the seed against the locked schemas + check §08 token budgets on the whole graph
python3 mcp_server/token_budget.py --validate

# data-quality lint (§01/§12): orphan KPIs, un-parented processes, broken references
python3 mcp_server/traceability.py

# walk an agent through the MCP tool loop, token counts on the wire
python3 mcp_server/scenario.py
```

**What to look for:** `scenario.py` shows one agent going through allow / escalate / deny /
out-of-scope, every response under budget. `traceability.py` flags exactly 3 planted defects
(2 orphan KPIs + 1 process with no strategic parent) — proof the linter works.

**Register the MCP server with an agent** (e.g. Claude Code). Use the **venv** Python so the
`mcp` package is on the path, and an **absolute** path to `server.py`:

```bash
claude mcp add continuum -- /ABS/PATH/TO/continuum-core/.venv/bin/python /ABS/PATH/TO/continuum-core/mcp_server/server.py
```

The agent then has `get_task_context`, `check_guardrail`, and `log_action`. (Running
`server.py` directly just blocks waiting on an MCP client over stdio — that's expected.)

### Phase 2 — govern the guardrails (edit without a deploy)

**What it is:** a web app where a process owner edits a Guardrail Policy; the edit is
validated, versioned, and recorded (ISO 9001 §7.5), and is immediately live for agents.

```bash
python3 governance/test_store.py    # prove the write path (14 assertions)
python3 governance/app.py           # then open http://localhost:8787
```

**Try it in the browser (http://localhost:8787):**
1. Click a process on the left (e.g. `CO.3.2.7`).
2. Change **Escalate if** from `risk_score > 0.7` to `risk_score > 0.95`.
3. Fill in a **Reason for change** (required) and click **Save new version**.
4. The version badge goes `v3 → v4`; the **History** and **Audit** tabs record the change.

**Prove "one source of truth"** — the edit is live for agents, no deploy. With the edit saved:

```bash
python3 -c "import sys; sys.path.insert(0,'mcp_server'); import continuum_core as c; g=c.Graph(); print(g.get('GuardrailPolicy','gr.CO.3.2.7')['version'], g.get('GuardrailPolicy','gr.CO.3.2.7')['escalate_if'])"
```

Expect `4 risk_score > 0.95`. Reset afterwards with `rm data/edits.log.jsonl` (back to v3).

**Also try:** enter an invalid `Escalate if` like `risk_score >>> 0.5` and Save — it's **refused**
with an error and the version does not change. Bad policy can't reach agents.

### Phase 3 — enforce the guardrail, and check the model against reality

**What it is:** the Enforcement Point (a real gate — the tool runs only on `allow`) wired to a
pilot agent, plus the Conformance Check that compares the model to reality (§06).

```bash
# a pilot agent; every action is routed through the Enforcement Point
python3 enforcement/pilot_agent.py
python3 enforcement/test_enforce.py     # 13 assertions incl. "tool runs ONLY on allow"

# §06 Conformance Check: documented model vs. reality → drift report (human-review-only)
python3 signal/conformance.py
python3 signal/test_conformance.py      # 8 assertions incl. "never mutates the model"
```

**What to look for:** `pilot_agent.py` shows the tool running only on the allow case, escalate
going to a human queue, deny/out-of-scope/rate-limit blocking. `conformance.py` reports 5 drift
types (including an agent that ran under a **stale guardrail**), each marked *needs human review*.

### Phase 4 — enforce everywhere, and read the standing report

**What it is:** enforcement across **all** agent-bound tasks, and the §05 strategy-to-execution
dashboard.

```bash
# run the Enforcement Point across all 8 agent-bound tasks AND keep the activity log
python3 enforcement/sweep.py --keep

# the §05 standing report (reads the log you just populated)
python3 dashboard/app.py                # then open http://localhost:8788
python3 dashboard/test_rollup.py        # 13 assertions

# verify the audit logs are tamper-free (after any activity)
python3 audit/verify.py                  # re-walks the hash chain + off-box anchor; exit 1 on tampering
python3 audit/anchor.py                   # take a signed off-box anchor of the chain, then verify
```

**What to look for on http://localhost:8788:** metric tiles (guardrail coverage **12% — 1/8
reviewed, honest**; traceability 88%; agent activity), each objective with its KPI status and the
agent-bound tasks beneath it, the coverage panel, and bottom-up traces. Two metrics read
`needs data` on purpose — they require human dispositions/timestamps (see [Known limits](#known-limits)).

> The dashboard is empty until you run `enforcement/sweep.py --keep` (or `pilot_agent`) to
> populate the agent action log it reads.

---

## Web apps

Two independent read/edit surfaces, different ports — you can run both at once:

| App | Command | URL | What |
|---|---|---|---|
| Governance editor | `python3 governance/app.py` | http://localhost:8787 | edit guardrails (Phase 2) |
| Strategy dashboard | `python3 dashboard/app.py` | http://localhost:8788 | standing report (Phase 4) |
| Process canvas | `python3 maps/app.py` | http://localhost:8789 | interactive §03 canvas — flowchart/RACI/checklist; view + edit guardrails/structure + author processes + bind agents to steps |
| Advisor | `python3 advisor/app.py` | http://localhost:8790 | AI window — analyze any process/guardrail/task/content vs best practices & standards |
| Ask the Agent | `python3 ask/app.py` | http://localhost:8791 | ask a plain-English question — the agent writes a read-only graph query, runs it, and answers with a table + Show query |

Each runs in the foreground; stop with `Ctrl-C`. To run one in the background:
`python3 governance/app.py &`. Change the port with `--port N` if 8787/8788 are taken.

---

## Data & reset

The model lives in `data/seed.json` (committed). Everything the running system writes is
**runtime state**, git-ignored, and safe to delete to reset:

| File | Written by | Deleting it… |
|---|---|---|
| `data/edits.log.jsonl` | governance edits (Phase 2) | reverts every guardrail to its `seed.json` version |
| `data/events.log.jsonl` | agent actions (Phase 3/4) | clears the dashboard's activity + the audit trail's agent side |
| `data/escalations.jsonl` | escalations (Phase 3/4) | empties the human escalation queue |
| `data/audit_heads.json` | the hash chain (all phases) | drops the tamper-evidence anchor — delete it alongside the logs, never on its own |

**Full reset to pristine:**

```bash
rm -f data/edits.log.jsonl data/events.log.jsonl data/escalations.jsonl data/audit_heads.json
```

Most test suites clean up after themselves; the two demos that intentionally leave data are
`enforcement/sweep.py --keep` (for the dashboard) and any guardrail you save in the governance UI.

---

## Known limits

These are gated on things this environment can't provide; each is declared with a real
interface and stubbed with a clear error or stand-in — never silently faked.

- **Live enterprise connectors** (Notion, Teams, Slack, Outlook, Gmail) need OAuth. They raise a
  clear error if called; `signal/connectors.py::FileConnector` + the `signal/*.sample.jsonl`
  fixtures stand in so the Conformance Check runs for real. Enable order is
  `SENSITIVITY_ORDER` in that file.
- **The pilot agent** is a deterministic Python loop, not a live LLM — it exercises the
  Enforcement Point exactly as a real MCP/Claude agent would, without needing model access.
- **Two §12 metrics** show `needs data`: *escalation precision* (needs humans to disposition
  escalations) and *drift-to-update latency* (needs finding + resolution timestamps). Supply
  dispositions to `dashboard/rollup.Rollup.metrics(...)` and escalation precision computes.
- **Guardrail coverage is 12% (1/8)** by design: only the KYC guardrail was reviewed/signed off;
  the rest run under defaults. That is the coverage metric working, not a bug.

## Troubleshooting

- **`ModuleNotFoundError: mcp / tiktoken / jsonschema`** — the venv isn't active or deps aren't
  installed. `. .venv/bin/activate && pip install -r mcp_server/requirements.txt`.
- **`Address already in use` (port 8787/8788)** — a server is already running. Reuse it, or start
  with `--port 8790`. Find/stop the old one: `lsof -ti:8787 | xargs kill`.
- **The dashboard is empty** — run `python3 enforcement/sweep.py --keep` first to populate
  `data/events.log.jsonl`.
- **A guardrail shows an unexpected version** — a prior governance edit is folded in.
  `rm data/edits.log.jsonl` resets to the `seed.json` versions.
- **`traceability.py` exited 1** — only happens on a hard broken reference. The normal state is
  exit 0 with the 3 expected warnings; if you see errors, a ref in `data/seed.json` is dangling.
- **Web app won't start from `.claude/launch.json` in some hosts** — run it directly instead:
  `python3 governance/app.py` (or `dashboard/app.py`). The direct command is the supported path.

---

*See [`README.md`](README.md) for architecture, [`DECISIONS.md`](DECISIONS.md) for why things are
the way they are, and each module's own `README.md` for detail.*
