-- Continuum object graph on Postgres (D48).
-- Lineage: continuum-platform/continuum-studio/supabase/migrations/20260828120000_init_object_graph.sql
-- (nodes / edges / node_events / agent_actions). Changes from that design, each
-- recorded in DECISIONS.md D48:
--   * every table is scoped by workspace_id (one governed model per workspace);
--     the Aug 28 RLS file named tenancy as the gap to close before multi-tenant use.
--   * node_events is the SOURCE OF TRUTH and the append point is application code,
--     not a trigger: only the app can produce the canonical hash-chained event
--     (prev_hash / hash over sorted-key JSON). `raw` keeps the exact bytes written,
--     so the chain re-verifies byte-for-byte. A trigger makes it append-only.
--   * nodes / edges are a rebuildable projection (seed baseline + every edit),
--     used for traversal and the optimistic-concurrency check.
--   * node_type is open (continuum-core's typed entities are validated by their
--     JSON Schemas in the app, not by a SQL check list that would need a migration
--     per new type).

create table if not exists workspaces (
  id           text primary key,                -- 'default', a model slug, or 'dir:<hash>' (tests)
  name         text not null,
  description  text not null default '',
  source       text not null default '',
  slug         text,                            -- the model's folder name (data/models/<slug>)
  registered   boolean not null default false,  -- true once it has a model.json (listed as a model)
  created_at   timestamptz not null default now()
);

-- Documents: seed.json, model.json, layout.json, portal.json, audit_heads.json …
create table if not exists docs (
  workspace_id text not null references workspaces(id) on delete cascade,
  name         text not null,
  body         jsonb not null,
  updated_at   timestamptz not null default now(),
  primary key (workspace_id, name)
);

-- Every append-only log line, chained (edits / events / proposals / policy) or
-- plain (escalations, archive, ledger, anchors).
create table if not exists node_events (
  id           bigserial primary key,
  workspace_id text not null references workspaces(id) on delete cascade,
  log          text not null,                   -- e.g. 'edits.log.jsonl'
  seq          integer not null,                -- 1-based position in that log
  chained      boolean not null,
  event_id     text,
  node_type    text,
  node_id      text,
  op           text,
  actor        jsonb,
  at           timestamptz not null default now(),
  raw          text not null,                   -- exact JSON line as written (hash input source)
  event        jsonb not null,                  -- the same line, queryable
  prev_hash    text,
  hash         text,
  unique (workspace_id, log, seq)
);
create index if not exists node_events_node_idx on node_events (workspace_id, node_id, at);
create index if not exists node_events_log_idx on node_events (workspace_id, log, seq desc);

-- Append-only: UPDATE is never allowed; DELETE only inside a transaction that
-- set continuum.allow_reset (demo / test resets and plain-log housekeeping).
create or replace function node_events_append_only()
returns trigger language plpgsql as $$
begin
  if tg_op = 'UPDATE' then
    raise exception 'node_events is append-only (ISO 9001 §7.5): updates are not allowed';
  end if;
  if coalesce(current_setting('continuum.allow_reset', true), '') <> 'on' then
    raise exception 'node_events is append-only (ISO 9001 §7.5): deletes are not allowed';
  end if;
  return old;
end;
$$;
drop trigger if exists node_events_append_only on node_events;
create trigger node_events_append_only before update or delete on node_events
  for each row execute function node_events_append_only();

-- Current-state projection.
create table if not exists nodes (
  workspace_id text not null references workspaces(id) on delete cascade,
  node_type    text not null,                   -- 'Process', 'Task', 'Capability', …
  id           text not null,
  name         text not null,
  status       text,
  version      integer,
  attrs        jsonb not null,                  -- the full entity
  source       text not null check (source in ('seed', 'edit')),
  updated_at   timestamptz not null default now(),
  primary key (workspace_id, node_type, id)
);
create index if not exists nodes_id_idx on nodes (workspace_id, id);

-- Every *_ref / *_refs field of a node, as a typed edge (edge_type = field name).
create table if not exists edges (
  workspace_id text not null references workspaces(id) on delete cascade,
  source_type  text not null,
  source_id    text not null,
  target_id    text not null,
  edge_type    text not null,
  primary key (workspace_id, source_type, source_id, target_id, edge_type)
);
create index if not exists edges_target_idx on edges (workspace_id, target_id, edge_type);

-- Lineage views: the Aug 28 schema's guardrails and agent_actions tables are
-- read models over the same source of truth.
create or replace view guardrails as
  select workspace_id, id, version, attrs from nodes where node_type = 'GuardrailPolicy';
create or replace view agent_actions as
  select workspace_id, node_id as task_id, event->'payload'->>'action' as action,
         event->'payload'->>'outcome' as outcome, event->'payload'->>'guardrail_version' as guardrail_version, at
  from node_events where log = 'events.log.jsonl';
