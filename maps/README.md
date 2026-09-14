# Process Maps (Canvas View) — §03, first slice

The in-app visual layer (Core Model §03 "visual for people"): every process in the
model rendered as a BPMN-style flow diagram, drawn from the same graph the agent,
governance, and dashboard layers read. Read-only; redrawn on each load.

## What each map shows

- **Flow** — `start → task → … → end`, tasks in `seq` order.
- **Agent step** — the task an agent is bound to, outlined in the accent colour with an **AI** badge and its performers (`role + agent`).
- **Escalation branch** — a dashed amber branch off an agent step showing where its guardrail sends the case to a human: `escalate → <role>  if <condition>`.
- **Task override** — a step with a stricter task-level guardrail (e.g. `IT.8.4.2.t3` "Grant admin access") outlined in amber with an **override** tag; human-only where the override forbids agent actions.
- **Header chips** — owner, guardrail version, KPIs, and linked risk.

## Run

```bash
python3 maps/app.py            # http://localhost:8789  (alongside governance :8787, dashboard :8788)
python3 maps/test_mapdata.py   # 10 asserts: structure, agent steps, escalation, override, fail-closed
```

## Files

- `mapdata.py` — assembles per-process map data from the graph (`all_maps`).
- `app.py` — stdlib HTTP server: `/api/maps` + the static canvas.
- `static/` — vanilla-JS SVG renderer (theme-aware, no build step, no diagram library).
- `test_mapdata.py` — structure assertions.

## Scope

This is the **read-only first slice** of §03's Canvas View. The full spec adds an
interactive three-pane editor and the other views of the same model (metro map,
RACI matrix, guided checklist) — the larger follow-on. The data (`mapdata.all_maps`)
is already shaped to feed those.
