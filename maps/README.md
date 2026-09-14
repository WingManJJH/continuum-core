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

## Authoring (drag palette)

The left-nav **palette** completes the §03 editor: drag a **"+ Step"** tile onto the
flow to insert a step at the drop position (append, prepend, or *between* two steps),
and **"+ New process"** authors a brand-new process — stamped with the permissive-but-
scoped **default guardrail** (§11) as a fresh, unreviewed instance (so §12 coverage
tracks that it still needs review). A new process opens an empty `start → end` flow
with a "drag a step here" hint. All authoring goes through the versioned, hash-chained
governance write path (`POST /api/task`, `POST /api/process`).

## Scope

The canvas now covers the full §03 loop: **view** (flowchart / RACI / checklist),
**edit** guardrails and step structure (rename / reorder / remove), and **author** new
processes and steps from the palette — all on the one graph, versioned, on the §7.5
trail. The one remaining structural write path is **agent-binding authoring** (attaching
an agent to a step from the canvas), noted for later.
