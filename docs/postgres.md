# Running Continuum on Postgres

Continuum runs on files by default: no setup, which suits offline work and the test suite. Set one environment variable and the same code runs on Postgres. Nothing else changes.

## Set up

```bash
pip install -r mcp_server/requirements.txt          # includes psycopg + psycopg-pool
export CONTINUUM_DATABASE_URL=postgresql://continuum_app:…@db-host:5432/continuum

python db/migrate.py                                 # creates / upgrades the schema (idempotent)
python db/import_files.py --dry-run                  # what would move from data/ and data/models/
python db/import_files.py                            # move file history into Postgres, chains re-verified
python run.py                                        # every app now reads and writes Postgres
```

Run the app as a **non-owner role**, so row-level security is a real second line behind the application (D59). Migrations and imports run as the owner; the apps never do:

```bash
python db/app_role.py --url <owner URL>          # creates/updates continuum_app; prompts for its password
python db/app_role.py --url <owner URL> --check  # report: no superuser/BYPASSRLS, DML only, RLS on, anon/authenticated locked out
export CONTINUUM_DATABASE_URL=postgresql://continuum_app@db-host:5432/continuum   # password via PGPASSWORD
```

`continuum_app` can log in and read/write rows in the Continuum tables, and nothing else. It does not own tables, so the workspace policies apply to it. It cannot run DDL, alter roles, or bypass the append-only trigger. On Supabase the pooler user is `continuum_app.<project-ref>`, and `app_role.py` also revokes the platform's default `anon`/`authenticated`/`service_role` grants on these tables.

If the database login is wrong or missing, startup stops with a single line (`Continuum did not start: cannot connect to Postgres: …`) instead of retrying.

## What is stored where

| Table | Holds |
|---|---|
| `workspaces` | One per governed model (`default`, or a model slug) |
| `docs` | The model's documents: `seed.json` baseline, `model.json`, canvas layout, portal links, heads anchor |
| `node_events` | **The source of truth.** Every log line: change control, agent actions, proposals, policy, escalations, retention. `raw` keeps the exact bytes, so hash chains re-verify exactly. Append-only: a trigger refuses UPDATE and DELETE |
| `nodes`, `edges` | Current state (seed + every edit) and every `*_ref` as an edge. Rebuildable at any time. Used for traversal (`node_descendants`, `node_ancestors`) and the concurrency check |

## Guarantees (identical on files and Postgres)

- **No silent overwrite.** A write carries the version it was based on. If someone saved first, it fails with a conflict (HTTP 409 in the apps) and nothing is written.
- **Serialized appends.** Appends to a log are serialized across threads and processes. Each chained append and its heads-anchor update happen together.
- **Tamper evidence.** Tamper evidence is the same SHA-256 chain as on files. Even a DBA who bypasses the trigger is caught by `audit/verify.py`.
- **Isolation.** Each request runs against its user's workspace. Row-level security scopes every row to the workspace the transaction declared.

## Tests

```bash
export CONTINUUM_TEST_DATABASE_URL=postgresql://…/continuum_test     # a throwaway database
python tests/run_all.py
# as the app role (what production runs): migrations use the owner URL, suites the app URL
CONTINUUM_TEST_DATABASE_OWNER_URL=postgresql://owner@…/continuum_test \
CONTINUUM_TEST_DATABASE_URL=postgresql://continuum_app:…@…/continuum_test python tests/run_all.py
```

This runs the Postgres contract suite (`db/test_postgres.py`) and replays every core and enterprise suite on Postgres. The only exceptions are the two suites that tamper with JSONL bytes directly; their Postgres equivalents are in the contract suite.
