-- Row-level security: a session sees only the workspace it set for the current
-- transaction (set_config('continuum.workspace', <id>, true) — the storage
-- backend does this on every transaction). Replaces the Aug 28 starter policies
-- ("any authenticated user may read and write"), as that file asked.
-- Table owners and superusers bypass RLS; run the app as a non-owner role (see
-- docs/postgres.md) so these policies are a real second line behind the app.
alter table docs enable row level security;
alter table node_events enable row level security;
alter table nodes enable row level security;
alter table edges enable row level security;

do $$
declare t text;
begin
  foreach t in array array['docs', 'node_events', 'nodes', 'edges'] loop
    execute format('drop policy if exists workspace_isolation on %I', t);
    execute format($p$create policy workspace_isolation on %I
                     using (workspace_id = current_setting('continuum.workspace', true))
                     with check (workspace_id = current_setting('continuum.workspace', true))$p$, t);
  end loop;
end $$;

-- Grant DML to the app role when it exists (created by ops, not by migrations).
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'continuum_app') then
    grant select, insert, update, delete on workspaces, docs, node_events, nodes, edges to continuum_app;
    grant usage, select on all sequences in schema public to continuum_app;
  end if;
end $$;
