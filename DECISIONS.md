# Continuum Core — Ratified Decisions

Authoritative record of decisions taken on top of *The Continuum Core Model* spec.
The RTF spec is the design; this file records where the build has since decided
something concrete. Newest first.

---

## 2026-09-13 — AI advisor window (analyze anything vs best practices & standards)

### D17 — Standards advisor + agent window
**Context:** asked for an AI window where any feature / data / process / content can be analyzed
against best practices and standards.
**Decision & build:** `advisor/` — a chat-style **agent window** (`app.py`, :8790) over a
deterministic **`RulesAdvisor`** engine. Point it at a process, guardrail, task, the whole model, or
paste content/data, and it returns a scored analysis with findings that **cite the standard each comes
from**: ISO 9001 §4.4 / §7.5 / §7.5.3, ISO 9004, APQC, and the Core Model doctrine §04 / §11 / §12,
plus least-privilege. Content is checked against an ISO 9001 §7.5 documented-information checklist;
pasted JSON is validated against the locked entity schema. `advisor/test_advisor.py` — 18 asserts.
Verified live: analyzed a guardrail (88%, "unreviewed default" flagged), the whole model (50%, real
coverage + traceability numbers), and a thin SOP (0% on §7.5 elements).
**The AI seam (honest):** a live natural-language reviewer is the **`LLMAdvisor`** — it needs model
access (API/OAuth), so it is declared and **refuses until provisioned** (exactly like the signal
connectors and the pilot agent); the RulesAdvisor stands in and is what the window uses now. Full
suite 164 asserts. Four apps now run together: governance :8787, dashboard :8788, canvas :8789,
advisor :8790.

---

## 2026-09-13 — Agent-binding authoring (make a step agent-run from the canvas)

### D16 — AgentBinding write path
**Context:** the one structural write path left after D15 — attaching an agent to a step.
**Decision & build:** `store.bind_agent(task_id, ...)` creates an `AgentBinding` (id derived from the
task, validated against the binding schema, pointing at the step) and adds it to the step's
`performed_by` — the binding is created first so the task-update validates. `store.unbind_agent`
reverses it: drops the agent from `performed_by` and **deprecates** the binding (retained, never
hard-deleted). Both go through the versioned, hash-chained §7.5 write path. Effect: the step now renders
as agent-run (AI badge + its guardrail's escalation branch) and counts toward §12 coverage. Canvas: the
step panel shows **"Make this step agent-run"** / **"Unbind agent"** (→ `POST /api/task` op bind/unbind).
`governance/test_binding.py` — 13 asserts. Verified live: bound an agent to `CO.3.2.7.t1` from the
canvas — the AI badge + escalation branch appeared, the binding is real and on the trail; chain intact.
Full suite 146 asserts.
**This closes every structural write path in §03.** The canvas is now a complete authoring surface:
view (flowchart/RACI/checklist), edit guardrails, edit + author process structure, and bind/unbind
agents — all on the one graph, versioned, tamper-evident. Open work is only the two env-gated items
(design-partner calls, connector OAuth).

---

## 2026-09-13 — Drag-palette authoring (§03 Canvas View, completed)

### D15 — Author brand-new processes + drag steps from a palette
**Context:** D14 let you edit an existing process's steps; the remaining §03 piece was authoring a
process from scratch and a drag palette.
**Decision & build:**
- **Process write path** — `store.add_process(code, name, owner_role, ...)`: validates the APQC-style
  code + owner, and stamps the new process with the **permissive-but-scoped default guardrail template
  (§11)** as a fresh **unreviewed** instance (`gr.<code>`, no review block → §12 coverage counts it as
  a default until reviewed). Both the guardrail and the process are created as versioned, chained events.
- **Positional insertion** — `add_task` gained `after` (append / `__start__` prepend / after a step),
  shifting the tail down as versioned updates, so a step can be dropped *between* existing ones.
- **Palette UI** — a left-nav palette with draggable "+ Step" / "+ Approval step" tiles and a
  "+ New process" button. Dragging a tile onto the flow inserts a step at the drop position (HTML5 DnD →
  `POST /api/task` with `after` computed from the drop x); a brand-new process renders an empty
  start→end flow with a "drag a step here" hint. `POST /api/process` reuses the store.
- `governance/test_authoring.py` — 18 asserts (create + auto-default-guardrail, append/insert/prepend,
  validation, chain-intact). Verified live in-browser: authored `QA.5.1.1` and built its flow by
  dragging Intake / Assess / Resolve into place, incl. a between-steps insert. Full suite 133 asserts.
**This completes the §03 Canvas View** buildable slice: view (flowchart/RACI/checklist), edit guardrails
and step structure, and author new processes — all on the one graph, versioned, on the §7.5 trail.
Agent-binding authoring (attaching an agent to a step) is the one remaining structural write path,
noted for later.

---

## 2026-09-13 — Task write path (edit process structure on the canvas)

### D14 — Structural editing: add / rename / reorder / remove steps
**Context:** D13's canvas edited guardrails; editing the process *structure* itself needed a Task write
path (the next extension).
**Decision & build:** added `store.edit_task / add_task / move_task / remove_task` — all through the
same event-sourced, hash-chained, §7.5 write path as guardrails: validated against the locked Task
schema **plus referential-integrity checks** (process exists, performers are real roles/agent bindings,
guardrail ref exists), versioned, reason required. `remove_task` **deprecates** (status change, retained
— never hard-deleted); the fold now overlays a deprecated payload so version+status carry. Deprecated
steps drop out of the canvas and the §12 coverage denominator (`mapdata` + `rollup` filter active). The
canvas gained a "+ Step" toolbar button and a per-step **structure panel** (rename, edit performers,
move up/down, remove) posting to `POST /api/task` (op = add/edit/move/remove → the store). New steps
inherit the process guardrail. `governance/test_taskedit.py` — 16 asserts. Verified live in-browser:
added/renamed(v2)/reordered/removed a step from the canvas, chain stayed intact. Full suite 115 asserts.
**Scope:** covers step add/rename/reorder/remove + performer edits. A drag-palette for authoring
brand-new processes and richer element editing round out the full §03 editor; the write path they'd use
is now in place.

---

## 2026-09-13 — Interactive process canvas (§03 Canvas View)

### D13 — Three-pane interactive editor with in-canvas guardrail editing
**Context:** D11 shipped the read-only maps; §03's Canvas View is a three-pane editor with
"click an element → its risks/KPIs/guardrail in a side panel" and multiple views of one model.
**Decision & build:** evolved `maps/` into a three-pane canvas — process nav · a center canvas with a
**view-switcher (Flowchart / RACI / Checklist)** · a contextual **properties panel**. Clicking a step
selects it (outlined) and shows its performers, data in/out, KPIs, override status, and its
**guardrail, editable in place**. The editor saves via `PUT /api/guardrail` → the *same tested
governance write path* (`store.edit_guardrail`): validated, escalate_if-linted, versioned, on the §7.5
trail, folded into the one graph — so a canvas edit is live for agents and shows on the dashboard, and
the canvas redraws with the new version. RACI and Checklist are derived client-side from the same map
data. `mapdata` now exposes the editable guardrail + data refs per task; `maps/test_mapdata.py` → 12
asserts. Verified live in the browser (both themes): clicked t3, edited its guardrail v3→v4 through the
canvas, confirmed via the MCP-side graph + intact audit chain. Full suite now 99 assertions.
**Scope:** in-canvas editing is **guardrails** (the "editable without a ticket" capability). Editing
process structure (add/move/rename steps) needs a task write path and palette-driven authoring — the
next extension; map data is already shaped for it.

---

## 2026-09-13 — Retention-policy engine (ISO 9001 §7.5.3)

### D12 — Retention & disposition scheduler
**Context:** the last flagged hardening piece — §7.5.3 requires a defined retention period and a
deliberate disposition schedule; the `deprecate` op existed but no scheduler did.
**Decision & build:** `governance/retention.py` classifies every audit record, applies a rule table
(retain period + action per class: `archive` / `dispose` / `review`), reports what is **due**, honors
**legal holds**, and `apply()` dispositions deliberately — copies due records to an append-only cold
archive and writes a per-record disposition ledger (who/when/action). It **never mutates the live
hash-chained logs** (tamper-evidence preserved) and **never auto-destroys** (`review` records are
surfaced for a human; `apply` is idempotent). `governance/test_retention.py` (16 assertions, incl.
"live chains still intact after disposition"). CLI `python3 governance/retention.py [--apply]`. Full
suite now 97 assertions.
**Honest boundary:** physically shredding a disposed record from a hash-chained log without breaking
the chain is a **seal-and-roll** deployment step (archive the old prefix under a new anchor, re-base
the live log) — out of scope; retention preserves the chained copy and flags the step. With D10's
off-box anchor, this closes the flagged audit hardening except the two named deployment steps (off-box
hosting of the key+notary, and seal-and-roll).

---

## 2026-09-13 — In-app process-map canvas (§03 Canvas View, first slice)

### D11 — Process Maps app (the visual layer)
**Context:** §03's human-facing "Canvas View" was the one planned product piece not built; the
buildable slices had focused on the model, agent, governance, dashboard, and audit layers.
**Decision & build:** `maps/` — a read-only app that renders every process as a BPMN-style flow from
the live graph: start→tasks→end, the agent-bound step highlighted with an AI badge, its guardrail
escalation branch to a human (`escalate → role if condition`), task-level overrides marked (e.g.
`IT.8.4.2.t3`), and a header of owner / guardrail version / KPIs / linked risk. `mapdata.all_maps`
assembles it; `maps/app.py` serves `/api/maps` + a vanilla-JS SVG canvas (theme-aware, no diagram
library); `maps/test_mapdata.py` (10 asserts). Runs alongside governance (:8787) and dashboard (:8788)
on :8789. Verified in the browser, both themes. Full suite now 81 assertions.
**Scope:** read-only first slice. The full §03 Canvas View adds an interactive three-pane editor and
the other views of the same model (metro map, RACI, guided checklist) — the larger follow-on; the map
data is already shaped to feed them.

---

## 2026-09-13 — Audit off-box anchor (co-forgery defense)

### D10 — HMAC-signed off-box anchor over both audit logs
**Context:** D9's hash chain is defeated by a party who rewrites both a log and its heads file into a
consistent chain — flagged as needing an off-box anchor. This closes it.
**Decision & build:** `audit/anchor.py` — `anchor_now()` takes a `combined_head` fingerprint over both
logs (one hash of both heads + counts), HMAC-signs it with a key held off the log-writer's box
(`CONTINUUM_AUDIT_KEY`), and publishes to a `Notary`. `verify_against_anchor()` re-derives each log's
head at the anchored count, checks it against the signed head (catches a rewritten prefix) and checks
the signature — returning verified / stale / TAMPERED. Wired into `audit/verify.py`.
`audit/test_anchor.py` (10 assertions) proves it detects the exact consistent co-forgery the chain
alone passes, plus signature/wrong-key/growth cases. Anchor store `data/audit_anchors.jsonl` (runtime,
git-ignored). Full suite now 71 assertions.
**Honest boundary (kept explicit):** security reduces to the HMAC key and the notary store being
off-box. `LocalNotary` keeps both on-box (faithful stand-in); `ExternalNotary` is the auth-gated real
write-once service and raises until provisioned (declared, not faked). Off-box *hosting* and a
retention-policy engine remain the named next steps.

---

## 2026-09-12 — Audit-log tamper-evidence

### D9 — Hash chain over the audit logs (ISO 9001 §7.5 hardening)
**Context:** the audit trail was §7.5-complete on content but tamper-evidence (a hash chain) was
flagged deferred in D6/AUDIT-LOG.md. This closes it.
**Decision & build:** every event now carries `prev_hash` + `hash` (SHA-256). Both writers
(`log_action`, `append_edit_event`) go through one choke point, `continuum_core._append_event`, so
the chain is maintained in exactly one place. A per-log heads anchor (`data/audit_heads.json`, runtime,
git-ignored) records the last hash + count. `verify_log()`/`verify_audit()` catch content edits,
deletions, insertions, reorders (via the chain) and trailing truncation / whole-log deletion (via the
heads anchor). CLI: `audit/verify.py`. Governance Audit tab shows a live intact/tampered badge.
Tests: `audit/test_audit_chain.py` (13 assertions: 10 tamper modes + reset-log hygiene). Envelope schema updated to
require `prev_hash`/`hash`.
**Honest boundary (kept explicit):** a party who can rewrite BOTH the log and the heads file can forge
a consistent chain; true tamper-*proofing* needs the head anchored off-box (external notarization /
append-only store). That, plus a retention-policy engine and one signed store for both logs, remain
the named next hardening steps.

---

## 2026-08-26 — Phase 4 kickoff

### D8 — Continuous enterprise connection, buildable slice (Phase 4 §09)
**Context:** Phase 4 = full guardrail enforcement across all agent-bound tasks + Teams/Slack/Gmail
signal + the §05 strategy-to-execution rollup dashboard as a standing report.
**Decision & build:**
- **Full enforcement across all agent-bound tasks** — `enforcement/sweep.py` drives the Enforcement
  Point across every agent-bound task (8/8), each gated (execute/escalate/deny). Fail-closed: a task
  with no effective guardrail is a coverage defect, surfaced by `dashboard/rollup.coverage()`.
- **§05 rollup dashboard** — `dashboard/` (engine `rollup.py` + web app + UI): top-down
  objective→KPI→process→agent-task with live activity, bottom-up agent-action→objective, §12
  guardrail coverage (fail-closed), and the §12 success-metric tiles. Reads the same graph + agent
  action log as everything else (one source of truth, read-only). Verified live in the browser. 13 asserts.
- **Teams/Slack/Gmail connectors** — added to `signal/connectors.py` as OAuth-gated stubs with their
  scopes, plus `SENSITIVITY_ORDER` (notion→teams→slack→outlook→gmail) for enable-sequencing.
**Honest edges (explicit, not hidden):**
- **All live connectors need OAuth, unavailable in this build** — the whole Phase-4 "enterprise
  connection" real-data path is gated on connector auth. FileConnector stands in; the buildable-here
  slice is the enforcement sweep + dashboard + engine, which are complete and tested.
- **Two §12 metrics are `needs_data`, not fabricated:** escalation precision (needs human escalation
  dispositions) and drift-to-update latency (needs finding + human-resolution timestamps). Guardrail
  coverage (12%), traceability completeness (88%), and agent-activity counts are computed live.
- Coverage is honestly **1/8 reviewed** — only the signed-off KYC guardrail; the other seven run
  under defaults. That is the §12 coverage metric doing its job, not a gap to paper over.

---

## 2026-08-26 — Phase 3 kickoff

### D7 — Signal & agent infrastructure shipped (Phase 3 §09)
**Context:** Phase 3 = MCP server ships (done Phase 1) + Enforcement Point built and wired to a
pilot agent + Signal Layer (Notion/Outlook first) feeding the Conformance Check (§06).
**Decision & build:**
- **Enforcement Point** (`enforcement/enforce.py`) — the generic gate of §04 Figure 3, now a real
  mediator: the underlying tool runs ONLY on an `allow` decision; `escalate` queues for a human and
  runs nothing; `deny` blocks and logs; stateful sliding-window **rate limiting** is enforced (closing
  the Phase-1 "not enforced" note). It holds no policy — reads the guardrail via continuum_core — and
  is the only sanctioned path to the tool (§11), enforced in code. Wired to a **pilot agent**
  (`enforcement/pilot_agent.py`) that can only act through the EP. 13 assertions pass.
- **Signal Layer + Conformance Check** (`signal/`) — `conformance.py` compares the documented model
  against reality (external signals + the agent execution log) and surfaces five drift types
  (stale_guardrail, off_model_action, coverage_gap, undocumented_step, shadow_process). Per §06 drift
  is surfaced only — every finding `requires_human_review`, nothing writes to the model. 8 assertions
  pass, including "conformance never mutates the model".
**Sub-decisions / honest edges:**
- **Live Notion/Outlook connectors need OAuth, unavailable in this build.** `signal/connectors.py`
  declares them with their required scopes and raises a clear error; `FileConnector` stands in with
  fixtures so the conformance engine is exercised for real. Swap connectors in once authorized —
  the interface is unchanged.
- Escalation queue (`data/escalations.jsonl`) and audit/edit logs are runtime state (git-ignored).
- Rate-limit state is in-memory (fine for the pilot); a shared store is a later hardening.

### D6 sequencing note
Phase 3 followed Phase 2 at the user's direction; the design-partner calls (D5) remain the one open
human action and are unblocked by — not dependent on — the agent infrastructure here.

---

## 2026-08-26 — Phase 2 kickoff

### D6 — Governance module shipped (Phase 2 §09)
**Context:** Phase 2 makes Guardrail Policy editable in the UI, risk/control linkage live, and
the audit log finalized to ISO 9001 §7.5.
**Decision & build:** shipped `governance/` — a stdlib web app (`app.py` + `static/`) over a
validated, event-sourced edit layer (`store.py`). An owner edits a guardrail → validated
against the locked schema, `escalate_if` linted through the Enforcement Point's own evaluator,
version bumped, reviewer+reason recorded (§7.5), committed to `data/edits.log.jsonl`. The core
`Graph` folds that log, so **the MCP path returns the edited policy immediately — one source of
truth, edits are data not deploys.** Verified end-to-end in the browser (gr.CO.3.2.7 v3→v4, live
for an agent; malformed edit refused). Audit log finalized in `schema/AUDIT-LOG.md`.
**Sub-decisions:**
- The **event envelope + two append-only logs** (change-control + agent-action) **are** the
  ISO 9001 §7.5 audit trail; no separate compliance workflow.
- **Deferred and flagged** (not silently omitted): audit-log tamper-evidence (hash chain),
  retention-policy engine, and consolidating the two logs into one signed store — all Phase-3+.
- `.claude/launch.json` (`continuum-governance`) is provided for interactive Claude Code; the
  canonical run is `python3 governance/app.py` after installing `mcp_server/requirements.txt`.

### D5 sequencing note
Phase 2 was started at the user's direction ahead of the D5 design-partner calls. The governance
UI doubles as the higher-fidelity design-partner demo (validation-guide.md §5), so building it
first de-risks those calls rather than pre-empting them.

---

## 2026-08-26

### D1 — Single-task-context budget raised 150 → 200 tokens
**Context:** §08 set the single-task-context budget at < 150. Validating with a real
tokenizer showed the §03 example package is ~136 tokens (not the "~70" the spec
annotates), and the whole-graph worst case is 147 (`SC.4.3.6.t3`) — leaving almost
no headroom for a larger process.
**Decision:** raise the budget to **200 tokens**. Keep the guardrail block inline in
the task context (the point of §03); do **not** split it behind a second tool call.
**Applied in:** `mcp_server/token_budget.py` (`BUDGETS`), `mcp_server/scenario.py`
(`BUDGET`). Worst case across the 8-domain graph is now 147/200.

### D2 — Restate the §03 compression claim
**Context:** §03 claims the context package is "8–15×" smaller than a BPMN/SOP
equivalent. Measured per single task it is ~3.4× (BPMN XML) / ~1.6× (prose SOP);
the 8–15× figure holds for a *whole-process* export vs. one task package.
**Decision:** state it as **"8–15× for a full-process export; ~3× per task."**
**Applied in:** `README.md` findings, `mcp_server/token_budget.py` compression section.
Still to do: fold the restatement into the spec's §03 prose at next spec revision.

### D3 — Default Guardrail Policy template signed off
**Context:** §13 step 3 called for the default template to be reviewed with the
fractional QMS/ISO advisor against ISO 9001 intent.
**Decision:** the default template is **signed off** for Phase 1 by the QMS/ISO advisor.
**Applied in:** `guardrail-template/default-guardrail-policy.json` (`review` note,
2026-08-26), `guardrail-template/DEFAULT-GUARDRAIL-TEMPLATE.md` (status header).

### D4 — Seed graph widened to 8 processes across 8 APQC domains
**Context:** §13 step 2 built the prototype against one hand-built process; step 4
of this round widened it to stress-test the schema and budgets against variety.
**Decision:** ship an 8-domain seed (CO, FN, SC, MS, IT, PD, HR, SV) with deliberate
edge cases: a financial-threshold `escalate_if` (FN `amount > 500`, SC
`amount > 10000 or vendor_risk > 0.6`), a **task-level guardrail override** stricter
than its process (`gr.IT.8.4.2.ADMIN` on `IT.8.4.2.t3`), an **orphan KPI**
(`kpi.unused_metric`), and a **process with no strategic parent** (`HR.7.2.5`).
**Applied in:** `data/seed.json`; new `mcp_server/traceability.py` linter surfaces the
planted defects (§01/§12). All §08 budgets still pass on the widened graph.

### D5 — Design-partner test instrumented for the next 3 calls
**Context:** §13 step 4 — test whether "guardrails a process owner can edit without an
engineering ticket" lands or needs reframing.
**Decision:** run the validation guide on the **next 3** pricing/ICP calls and log the
three columns (spontaneous frame / A-B framing winner / Fail-A · Fail-B · Supported).
**Applied in:** `design-partner/call-log.md` (ready-to-fill tracker + rollup). The calls
themselves are a human action; the instrument is in place.
