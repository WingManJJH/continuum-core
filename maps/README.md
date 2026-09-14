# Process Canvas (interactive §03 Canvas View)

The in-app visual editor (Core Model §03 "visual for people"): a three-pane canvas
over the one graph the agent, governance, and dashboard layers all read.

## Three panes

- **Left — processes.** Pick any of the 8 processes.
- **Center — canvas with a view-switcher.** Three **views of one model** (§03):
  - **Flowchart** — BPMN-style `start → task → end`; the agent-bound step is
    outlined with an **AI** badge and shows its guardrail escalation branch to a
    human; task-level overrides marked; **click a step to select it**.
  - **RACI** — a matrix (roles × tasks, R / A / C) *derived from the model*, not
    hand-maintained.
  - **Checklist** — a guided, tickable run-list of the process's steps.
- **Right — contextual properties.** For the selected step: performers, data
  in/out, KPIs, task-level override — and its **guardrail, editable in place**.

## Editing is real — and one source of truth

The guardrail editor in the properties panel saves through the **same tested
governance write path** (`store.edit_guardrail` via `PUT /api/guardrail`): the edit
is validated, `escalate_if`-linted, **versioned** (new version, no deploy), recorded
on the ISO 9001 §7.5 trail, and folded into the same graph. So a change made on the
canvas is instantly live for agents, shows on the dashboard, and the canvas redraws
with the new version — exactly the governance app's guarantee, from the map.

## Run

```bash
python3 maps/app.py            # http://localhost:8789 (alongside governance :8787, dashboard :8788)
python3 maps/test_mapdata.py   # 12 asserts: structure, agent steps, escalation, override, editor payload
```

## Files

- `mapdata.py` — assembles per-process map data (incl. the editable guardrail) from the graph.
- `app.py` — stdlib server: `GET /api/maps` + `PUT /api/guardrail` (reuses the governance store).
- `static/` — vanilla-JS three-pane canvas: SVG flowchart + RACI + checklist + properties/editor (theme-aware, no diagram library).
- `test_mapdata.py` — structure + editor-payload assertions.

## Scope

The interactive editing here is **guardrails** (the "editable without an engineering
ticket" capability). Editing the process structure itself (add/move/rename steps)
needs a task write path and is the next extension; the palette-driven authoring and
richer element editing round out the full §03 editor.
