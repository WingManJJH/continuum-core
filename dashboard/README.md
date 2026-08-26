# Strategy → Execution Dashboard — Phase 4

The standing leadership report (Core Model §05): because the spine is one graph,
tracing strategy to the agent action executing it — and back — is a walk, not a
special request to engineering.

## What it shows

- **Top-down** — each Strategic Objective → its KPIs (live value vs. target, on/off
  target) → the processes tracked → the **agent-bound tasks** beneath them, with the
  guardrail version each runs under and what the agent actually did (success / escalated
  / denied) in the current log.
- **Bottom-up** — agent activity rolled back up: task → process → KPI → objective.
- **§12 guardrail coverage** — every agent-bound task and whether it runs under a
  *reviewed, versioned* guardrail or a default. Fail-closed: a task with no effective
  guardrail is a defect, surfaced here.
- **§12 success metrics** — guardrail coverage, traceability completeness, and agent
  activity are computed live. **Escalation precision** and **drift-to-update latency**
  are shown as `needs data` — they require human escalation dispositions and
  finding/resolution timestamps (a connector-auth-gated Phase-4 signal), and are marked
  honestly rather than fabricated. Supply dispositions to `Rollup.metrics(...)` and
  escalation precision computes.

## Run

```bash
# populate the agent action log the dashboard reads
python3 enforcement/sweep.py --keep

python3 dashboard/app.py           # http://localhost:8788  (read-only)
python3 dashboard/rollup.py        # same report to the terminal
python3 dashboard/test_rollup.py   # 13 assertions
```

Reads the same graph (`data/seed.json` + governance edits) and agent action log
(`data/events.log.jsonl`) the rest of the system uses — one source of truth, no
separate reporting store. Read-only: the dashboard never writes.

## Files

- `rollup.py` — the engine: `strategy()`, `bottom_up()`, `coverage()`, `metrics()`.
- `app.py` — stdlib HTTP server exposing `/api/rollup` + the static dashboard.
- `static/` — vanilla-JS leadership view (no build step).
- `test_rollup.py` — top-down / bottom-up / coverage / metrics assertions.
