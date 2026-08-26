# Continuum Core — Ratified Decisions

Authoritative record of decisions taken on top of *The Continuum Core Model* spec.
The RTF spec is the design; this file records where the build has since decided
something concrete. Newest first.

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
