# Continuum Core Model — Phase 1 Data Model (LOCKED)

**Status:** Locked for Phase 1 · **Version:** v1 · **Date:** 2026-08-25
**Source of truth:** *The Continuum Core Model* §02 (unified object model) and §04 (guardrails).
**Decision this file records:** these schemas are the *literal* Phase 1 data model, not a placeholder to revisit (Core Model §13, step 1). Changes after lock go through the versioning discipline below, not by editing intent.

This is the answer to §09's "the schema itself must be agent-ready from Phase 1." Live guardrail *enforcement* and external connectors do not ship until later phases, but the schema they will read is fixed now, because retrofitting a schema after the fact is far more expensive than designing it in from day one.

---

## The eight entities

Five sit on the spine (Figure 1); three attach to it.

| Entity | Role on the spine | Schema file |
|---|---|---|
| **Strategic Objective** | top — intent | `strategic-objective.schema.json` |
| **KPI** | measures the objective | `kpi.schema.json` |
| **Process** | ISO 9001 §4.4 object; the graph's join point | `process.schema.json` |
| **Task / Activity** | one step; the unit an agent binds to | `task.schema.json` |
| **Human Role** | performs / owns / receives escalations | `human-role.schema.json` |
| **Agent Binding** | performs (autonomously, under a guardrail) | `agent-binding.schema.json` |
| **Guardrail Policy** | attaches to Process/Task; the enforcement layer | `guardrail-policy.schema.json` |
| **Risk & Control** | attaches to Process; register entry | `risk-control.schema.json` |

Every write to any of them goes through `_envelope.event.schema.json`.

## The connected chain (Figure 1, encoded)

```
Strategic Objective --targets--> KPI --tracked by--> Process --decomposes into--> Task --performed by--> {Human Role | Agent Binding}
                                                         |                              |
                                            (governs) Guardrail Policy      (may override) Guardrail Policy
                                            (carries) Risk & Control
        <---------------------- actual performance rolls up (run-time feedback) ----------------------
```

- **Design-time decomposition** (solid arrows) is expressed by the `*_refs` / `*_ref` fields pointing *down* the chain (objective→kpi→process→task→role/agent).
- **Run-time feedback** (the dashed teal arrow) is `KPI.live_value` / `as_of`, written by the signal layer and rollup (§05, §06), read back by the objective through `kpi_refs`.

## ID conventions (stable join keys)

| Prefix | Entity | Example | Notes |
|---|---|---|---|
| *(APQC code)* | Process | `CO.3.2.7` | id **==** apqc_code. The canonical key everything else references. |
| `<apqc>.t<n>` | Task | `CO.3.2.7.t3` | Self-locating: contains its process code. |
| `obj.` | Strategic Objective | `obj.reduce_onboarding_friction` | |
| `kpi.` | KPI | `kpi.time_to_verify` | |
| `role.` | Human Role | `role.ops.support_tier1` | Also used for owners & escalation paths. |
| `agent.` | Agent Binding | `agent.kyc_verifier` | |
| `gr.` | Guardrail Policy | `gr.CO.3.2.7` | Version-pinned form: `gr.CO.3.2.7.v3`. |
| `rc.` | Risk & Control | `rc.kyc_false_verify` | |
| `evt_` | Event | `evt_01J...` | ULID, sortable. |

APQC PCF codes are the **join key**, not just a starter content pack (§10): a KPI, a guardrail, and an agent binding for the same process all key off the same `apqc_code`.

## Guardrail inheritance (the one rule that isn't obvious)

1. A `GuardrailPolicy` attaches to a **process** (`attaches_to.kind = "process"`) or a **task** (`= "task"`).
2. A task's **effective guardrail** = its own `guardrail_ref` if non-null, else the owning process's `guardrail_ref`.
3. Resolution is deterministic and computed in `continuum_core.effective_guardrail()`, never stored denormalized — so a process-level policy edit propagates to every inheriting task with no fan-out write.
4. The version an agent acts under is pinned at read time and cited on every logged action (§04).

## Versioning discipline (why every entity has `version` + `status`)

- **No overwrites.** Every change is a new event (`_envelope`), producing a new `version`. This is ISO 9001 §7.5 document control *and* event-sourcing, one mechanism (§07, §10).
- **No hard deletes.** Retirement is `status: deprecated` via `op: deprecate`. Records are never destroyed — audit trails and rollback depend on it.
- **Current state is a fold** over an entity's event stream. `payload` stores the whole entity per event (snapshot-per-event), so any historical version reconstructs without replaying deltas.
- **Agents cite versions.** `log_action` requires the `guardrail_version` the agent read, so a dispute resolves against the policy that actually applied — not whatever it says today.

## ISO / APQC provenance (per field)

| Requirement | Where it lives |
|---|---|
| ISO 9001 §4.4 — process owner | `Process.owner_role` (single accountable role) |
| ISO 9001 §4.4 — inputs/outputs | `Process.inputs` / `outputs` (typed refs, enabling conformance checking §06) |
| ISO 9001 §4.4 — sequence & interaction | `Process.interfaces.upstream/downstream`, `Task.seq` |
| ISO 9001 §4.4 — monitoring | `Process.kpi_refs` → `KPI` |
| ISO 9001 §7.5 — document control | `version` + event-sourced writes on every entity |
| ISO 9004 — maturity (PDCA) | `Process.maturity_score` (1–5); the improvement loop is §06 |
| APQC PCF — classification / join key | `Process.apqc_code` (== id) |

## What is deliberately **not** in these schemas

Canvas decorative properties — position, color, label placement — are real data but live in the rendering layer, never in these entities and never in the agent-facing package (§08 discipline). Keeping them out is what holds the agent context package inside its token budget.

## Validation

All eight entity schemas + the envelope are JSON Schema draft 2020-12. Seed data in `../data/` validates against them; run:

```bash
python3 continuum-core/mcp_server/token_budget.py --validate
```

## Lock changelog

- **v1 (2026-08-25)** — Initial lock. Eight entities + event envelope. Encodes Core Model §02/§04 verbatim; no fields added beyond the spec's stated ones except explicit `id`/`version`/`status` scaffolding and the `_envelope` required by §07's event-sourced write discipline.
