-- Recursive-CTE traversal over edges (lineage: 20260828120100_graph_traversal.sql),
-- now workspace-scoped.
create or replace function node_descendants(ws text, start_id text, max_depth int default 6)
returns table (id text, node_type text, name text, depth int, edge_type text)
language sql stable as $$
  with recursive walk(id, depth, edge_type) as (
    select start_id, 0, null::text
    union all
    select e.target_id, walk.depth + 1, e.edge_type
    from edges e join walk on e.source_id = walk.id
    where e.workspace_id = ws and walk.depth < max_depth
  )
  select distinct on (n.id) n.id, n.node_type, n.name, walk.depth, walk.edge_type
  from walk join nodes n on n.id = walk.id and n.workspace_id = ws
  where walk.depth > 0
  order by n.id, walk.depth;
$$;

create or replace function node_ancestors(ws text, start_id text, max_depth int default 6)
returns table (id text, node_type text, name text, depth int, edge_type text)
language sql stable as $$
  with recursive walk(id, depth, edge_type) as (
    select start_id, 0, null::text
    union all
    select e.source_id, walk.depth + 1, e.edge_type
    from edges e join walk on e.target_id = walk.id
    where e.workspace_id = ws and walk.depth < max_depth
  )
  select distinct on (n.id) n.id, n.node_type, n.name, walk.depth, walk.edge_type
  from walk join nodes n on n.id = walk.id and n.workspace_id = ws
  where walk.depth > 0
  order by n.id, walk.depth;
$$;

-- §01/§12 data-quality check: processes and KPIs with no relationship at all.
create or replace view orphaned_nodes as
  select n.workspace_id, n.id, n.node_type, n.name
  from nodes n
  where n.node_type in ('Process', 'KPI') and coalesce(n.status, 'active') <> 'deprecated'
    and not exists (select 1 from edges e where e.workspace_id = n.workspace_id
                    and (e.target_id = n.id or e.source_id = n.id));
