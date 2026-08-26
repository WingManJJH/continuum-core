# Audit Log — finalized against ISO 9001 §7.5 (Phase 2)

**Status:** Finalized for Phase 2 · **Date:** 2026-08-26
**Source:** Core Model §04 (versioned guardrails), §07 (event-sourced writes), §09 Phase 2, §10.
**Decision recorded:** the event envelope + the two append-only logs below **are** the
audit trail; ISO 9001 §7.5 document control falls out of how writes are stored, not a
separate compliance workflow (Core Model §10). This closes Phase 2 item "audit log schema
finalized against ISO 9001 §7.5".

## Two logs, one envelope, one trail

Every write is an immutable event conforming to [`_envelope.event.schema.json`](_envelope.event.schema.json).
Events live in two append-only logs by origin, unioned into one timeline by the governance
audit view (`governance/store.py::audit`) and the UI's Audit tab:

| Log | Written by | Event shape | Meaning |
|---|---|---|---|
| `data/edits.log.jsonl` | Governance module (a human, via the UI) | `op: update`, full entity `payload`, `from_version`→`to_version`, `reason` | **Change control** — a policy/model edit |
| `data/events.log.jsonl` | Agents, via `log_action` over MCP | `op: update`, action `payload` citing `guardrail_version` | **Agent action** — what an agent did, under which policy version |

Both are runtime state (git-ignored). Current entity state is a fold of the seed baseline
plus `edits.log.jsonl` (`continuum_core.Graph.apply_edit_log`), so the state an agent reads
is exactly the state the last governance edit produced.

## ISO 9001 §7.5.3 (control of documented information) — requirement → mechanism

| §7.5 requirement | How it is satisfied | Field / mechanism |
|---|---|---|
| **Identification** | Every entity has a stable id + monotonic `version`; each event has a ULID `event_id` | `entity_id`, `to_version`, `event_id` |
| **Version control** | Every edit is a new version, never an overwrite; prior versions are reconstructable (snapshot-per-event) | `op`, `from_version`, `to_version`, full `payload` |
| **Review & approval** | Each guardrail edit carries reviewer + timestamp + reason; an empty reason is refused at write time | `payload.review.{reviewed_by, reviewed_at, note}`, enforced in `store.edit_guardrail` |
| **Author / accountability** | Who caused the write, human or agent, is on every event | `actor.{kind, id}` |
| **Traceability of use** | An agent action cites the exact policy version it acted under, so a dispute resolves against the policy that actually applied | `events.log.jsonl` `payload.guardrail_version` |
| **Protection from loss/alteration** | Append-only logs; no in-place edit, no hard delete (retirement is `op: deprecate`) | envelope `op` enum has no `delete` |
| **Retention & disposition** | Full history retained as the event stream; disposition is `deprecate`, never destruction | `status: deprecated` via `op: deprecate` |

## Retention & tamper-evidence — Phase 2 scope vs. later

**In Phase 2 (built):** append-only files, full snapshot per event, reviewer/reason on every
change-control event, version citation on every agent action, unified audit view.

**Deferred (flagged, not silently omitted):**
- **Tamper-evidence** — a hash chain (`prev_event_hash`) over the log for cryptographic
  append-only proof. The envelope has room; not wired in Phase 2. Add before an external audit
  that requires it.
- **Retention policy engine** — automatic disposition schedules per entity class. The `deprecate`
  op and status exist; a scheduler does not yet.
- **Segregation of the two logs into one signed store** — fine as two files for the prototype;
  a production deployment should land both in one appended, access-controlled store.

These are the honest edges of the Phase-2 audit trail: the §7.5 *content* requirements are met;
the *tamper-evidence* hardening is a named Phase-3+ item, not an assumed given.
