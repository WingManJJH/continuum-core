# Consolidation analysis: continuum-core and the EA/GRC build

**Date:** 2026-10-01 · **Owner:** Jeffrey Hunt · **Status:** decided (direction from Jeffrey, 2026-10-01)

## 1. Summary

There are three codebases today. They overlap in several places, and none of them depends on another:

| Codebase | Language | What it is | Size | Tests |
|---|---|---|---|---|
| **continuum-core** (GitHub `WingManJJH/continuum-core`) | Python 3.11+ | The governed model: typed entities, hash-chained change control, guardrail enforcement, MCP agent server, plus five web apps (governance, dashboard, canvas, advisor, ask), approvals, CAPA, X-matrix, BPMN/Visio import and export, and model importers | ~13.1k lines Python, ~7k lines JS/HTML/CSS | 38 suites, 470 assertions, CI on 3.11 and 3.12, PR-gated `main` |
| **continuum-platform** (Aug 28, drive only) | JS + SQL | Studio source (single-file artifact), a Node MCP server reading Studio exports, and the **Supabase Postgres schema** (nodes / edges / guardrails / node_events, traversal CTEs, pgvector, RLS) | small | 43 MCP + 10 seed |
| **EA/GRC build** (Sep 30 overnight, drive + project) | JS + SQL | A shared JS rules core (Ripple, Assure, Vitals, Atlas, ISO 9001/9004 packs), a Studio enterprise layer, and a Node/Postgres platform with versioned imports | ~5k lines | 25 core + ~40 Studio e2e + 36 platform |

**Finding:** the EA/GRC build duplicated two things continuum-core already does better: the event store/audit, and the MCP agent server. It also built a REST backend parallel to continuum-core's apps. Its *new* parts don't exist anywhere else:

- the five building blocks;
- Ripple, Assure, Vitals and Atlas;
- the ISO packs;
- versioned imports.

**Recommendation (adopted):** one codebase, **continuum-core**. Port the new parts into it, move its storage to Postgres on the Supabase schema lineage, and build the multi-user app there. Nothing in this work needs to run as a separate code base. Two pieces stay in JavaScript, in the same repo, because they run in a browser:

- the offline Studio artifact;
- the canvas client.

## 2. Side-by-side

| Capability | continuum-core | EA/GRC build | Decision |
|---|---|---|---|
| Entity model | 16 typed entities with JSON Schemas, refs as fields (`process_ref`, `guardrail_ref`) | 7 node types, generic `edges` table | **Keep continuum-core's model.** Add Capability, Application, Obligation, Control, Risk as new locked schemas in the same style |
| Risk and control | `RiskControl`: one risk plus one control per process | Separate Risk and Control, many-to-many | **Add separate `Risk` and `Control`; keep `RiskControl`** (nothing breaks). Assure and Ripple read a RiskControl as a paired risk plus control. An optional split tool converts it |
| Change control and audit | Snapshot-per-event JSONL, SHA-256 hash chain, heads anchor, off-box anchor, verify | Postgres `node_events` and replay verify, no hash chain | **Keep continuum-core's chain.** Store the same events in Postgres with identical hashes, so `verify` works on either backend |
| Agent MCP server | Python, 5 decision branches, Enforcement Point, token budgets | Node, 5 tools | **Keep Python.** Add `get_impact` (Ripple) and `get_vitals` as tools. Retire both Node MCP servers |
| Rules: Ripple, Assure, Vitals, Atlas | None (the Advisor scores against ISO; dashboard rollup) | JS core, 25 tests | **Port to Python** (`enterprise/`). Keep the JS core only for the offline Studio. Shared fixtures prove both give identical answers |
| Versioned imports | None. `builder/model_import.write_model` **overwrites `seed.json`**; BPMN import always creates a new process | Batches, baselines, staged changes, accept/reject, revert | **Port to Python on Postgres.** Re-importing a model then never overwrites an edited record |
| Postgres | None (files) | Migrations 001–004 | **New `db/migrations/` in continuum-core,** descended from the Supabase schema (§4) |
| Web apps | 5 stdlib HTTP apps, SSE, approvals, portal | REST only | **Keep continuum-core's apps** and make them multi-user (§5) |
| Identity | Actor taken from the request body (`payload["actor"]`), so anyone can claim to be anyone | `X-Continuum-Actor` header (also trusted) | **Replace both** with signed sessions (§5) |
| Active model | **Process-global** `set_active_model()`: one user switching model switches it for everyone | One database per workspace | **Per-request workspace** (thread-local), resolved from the signed-in user |
| Studio (single-file artifact) | — | Enterprise layer patched in via `build.py` | **Move Studio source into continuum-core `studio/`**, built by one script with the same tests. Studio stays an offline/demo surface; the server is the system of record |

## 3. Why one codebase, and why continuum-core

1. **It has the most governed value.** It has 470 CI assertions, a tamper-evident audit, approvals, CAPA, guardrail enforcement and 43 ratified decisions. Rebuilding that on the Node platform would take weeks and add risk with no customer benefit.
2. **One rules engine of record.** With two backends, what a change "touches" could differ by surface. One Python engine on the server makes that impossible. The browser-only JS copy is held to it by parity tests in CI.
3. **ISO 9001 §7.5 and 9004 §11 (learning).** There is one change-control mechanism, one test standard, one CI gate and one decision log (`DECISIONS.md`).
4. **The other pieces don't need separate runtimes.** The Studio is a static file, the JS core is a library, and the Node platform's job is fully covered once its features are ported.

**What should stay separate:** nothing at the repository level. Keep the browser code (Studio, canvas JS) as separate *build outputs* inside the same repo.

## 4. Postgres design (Supabase lineage, extended)

Each storage path is one call, so the backend swap is contained. All model writes go through `append_edit_event` and `_append_event`, and all reads go through `Graph.__init__` / `apply_edit_log`. A `storage` module puts a backend interface behind those calls:

- **FileBackend:** today's behaviour, unchanged. It is the default when no database is configured, and is used by the existing tests and offline work.
- **PostgresBackend:** selected by `CONTINUUM_DATABASE_URL`.

| Table | Lineage | Purpose |
|---|---|---|
| `workspaces` | new (the RLS migration noted tenancy as missing) | One governed model per workspace. Replaces `data/models/<slug>/` |
| `nodes` | Supabase `nodes`, plus `workspace_id`; `node_type` widened to every entity type | Current-state projection: full entity in `attrs`, plus `version` and `status` |
| `edges` | Supabase `edges`, plus `workspace_id` | Derived from the `*_ref` fields on each write, so the Supabase traversal CTEs (`node_descendants` / `node_ancestors`) work for Ripple at scale |
| `node_events` | Supabase `node_events`, plus `workspace_id`, `log` (edits / events), `seq`, `prev_hash`, `hash`, `event` | **Source of truth.** Same canonical JSON and SHA-256 as the file chain |
| `seeds` | new | The baseline each workspace was created from (today's `seed.json`) |
| `import_batches`, `import_baselines`, `staged_changes` | EA/GRC migration 004 | Versioned imports |
| `users`, `memberships`, `sessions` | new | Multi-user (§5) |
| `app_state` | new | Today's side files (canvas layout, portal links, active-model pointer) |

**Changes to the Supabase design (logged as decisions):**

1. **The append point is application code, not a trigger.** The Supabase `log_node_event` trigger can't produce the canonical hash-chained event. A trigger on `node_events` *refuses* UPDATE and DELETE, so the log stays append-only even against direct SQL.
2. **RLS:** policies scope every table by `workspace_id = current_setting('continuum.workspace')`. This replaces the "any authenticated user" starter policies, as their own comment asked.
3. **Concurrency:** each write takes a per-workspace advisory lock and checks the entity's stored version against the writer's `from_version`. A stale write fails with a conflict (HTTP 409) instead of silently winning.
4. **pgvector** stays optional: it is a separate migration, applied only when the extension exists.

## 5. Multi-user web app (in continuum-core)

| Need | Design |
|---|---|
| Sign-in | One `auth` module shared by all apps. OIDC (Microsoft Entra ID first, any OIDC issuer by config) for production. A development sign-in is used only when `CONTINUUM_AUTH=dev`, for local work and tests. Sessions are HMAC-signed cookies, so they work across the five app ports and behind one reverse proxy |
| Who did it | The actor comes **only from the session**; request-body `actor` is ignored when auth is on. Every event records the user, their workspace role and their HumanRole |
| Roles | Workspace membership roles: viewer, editor, approver, admin. Each user can be linked to a model `HumanRole`, so RACI, approvals and audit name real people |
| Tenancy | Workspaces in one database, scoped by RLS. A user only sees workspaces they belong to. The active model is per user, not global |
| Live collaboration | The SSE stream watches the workspace's event sequence (Postgres) instead of file sizes. A stale edit returns 409 and the UI reloads the record |
| EA modules | New canvas views: Capabilities (Atlas), Applications and agents, Obligations (Assure, ISO 9001/9004 packs), Risks and controls, Ripple on any record, Vitals |
| Import review | Imports list (who, when, what changed); staged changes with a field-by-field diff; accept / reject; revert a whole import |
| Admin | Members and roles; invite by email; link a user to a HumanRole |

## 6. Plan and test standard

All work goes on a feature branch in continuum-core, in reviewable commits. **One command runs every suite:**

```
python tests/run_all.py
```

It runs the 38 existing suites, the new suites, the harness, the JS parity check (when Node is present), and the Postgres suites (when a test database is configured). CI runs the same command with a Postgres service.

| Step | Content | Done when |
|---|---|---|
| 1 | Branch and the standard test runner; CI uses it | 470 assertions green through `run_all` |
| 2 | Five new schemas and their write paths; ISO packs | Schema, store and Assure suites green |
| 3 | Ripple, Assure, Vitals and Atlas in Python | Parity with the JS core on shared fixtures |
| 4 | Storage backend and Postgres migrations | Existing suites unchanged on the file backend; a backend contract suite runs the same governed scenarios on **both** backends; the hash chain verifies on Postgres |
| 5 | Versioned imports on Postgres | The 11 overnight review scenarios pass in Python |
| 6 | Multi-user: auth, roles, workspaces, SSE | Two-user browser test: separate sessions, live update, 409 on a stale edit, no access across workspaces |
| 7 | EA and import-review UI | Browser e2e green |
| 8 | Studio source into `studio/`; retire the Node platform | Studio regression test identical; build log and decisions updated |

**Delivery:** git commits on the branch, handed back to the drive repo as a git bundle and fetched into a branch there. Nothing is pushed to GitHub from here (no credentials, and `main` is PR-gated). You open the PR.

## 7. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Backend swap changes behaviour | One storage interface; a contract suite runs on both backends; identical hashes across backends |
| Global state (module singletons, active model) leaks between users | Per-request workspace context; a test with two concurrent users |
| JS and Python rules drift | Shared fixtures in CI; Python is the system of record |
| Scope is large | Each step is a working, tested commit; the order puts value first (EA/GRC, then Postgres, then multi-user) |
