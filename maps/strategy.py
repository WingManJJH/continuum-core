"""
Strategy layer (Phase 2) — OKR board, X-matrix, and strategy-alignment data.

Assembles, from the one governed graph, how the whole business ladders up:
Enterprise mission/vision/values -> breakthrough & annual objectives (Hoshin) ->
KPIs / key results (with fulfilment status and a KPI hierarchy) -> the improvement
initiatives and the processes (at any level 1-5) that deliver them.

Process↔objective linkage is derived two ways and unioned: an explicit
`Process.objective_refs`, and the KPI path (a process moves a KPI that serves an
objective) — so alignment shows up from existing data, and gaps are surfaced
honestly (objectives with no supporting process; processes tied to no objective;
KPIs off target). Read-only; the same source of truth as every other view.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402


def kpi_status(k: dict) -> str:
    lv = k.get("live_value")
    if lv is None:
        return "no_data"
    if k.get("direction") == "lower_is_better":
        return "on_target" if lv <= k["target"] else "off_target"
    return "on_target" if lv >= k["target"] else "off_target"


def strategy(g: cc.Graph | None = None) -> dict:
    g = g or cc.Graph()
    ent = next((e for e in g.all("Enterprise") if e["status"] == "active"), None)
    objs = [o for o in g.all("StrategicObjective") if o.get("status") == "active"]
    kpis = {k["id"]: k for k in g.all("KPI") if k.get("status") == "active"}
    procs = [p for p in g.all("Process") if p["status"] == "active"]
    inits = [i for i in g.all("Initiative") if i.get("status") == "active"]

    # process -> objectives (explicit refs ∪ via KPI links)
    kpi_obj = {kid: set(k.get("objective_refs", [])) for kid, k in kpis.items()}
    proc_objs, obj_procs = {}, {}
    for p in procs:
        s = set(p.get("objective_refs", []))
        for kref in p.get("kpi_refs", []):
            s |= kpi_obj.get(kref, set())
        proc_objs[p["id"]] = s
        for oid in s:
            obj_procs.setdefault(oid, []).append({"id": p["id"], "name": p["name"], "parent_ref": p.get("parent_ref")})

    # KPI hierarchy (children)
    kpi_children = {}
    for kid, k in kpis.items():
        if k.get("parent_ref"):
            kpi_children.setdefault(k["parent_ref"], []).append(kid)

    def kpi_card(kid: str) -> dict:
        k = kpis.get(kid)
        if not k:
            return {"id": kid, "name": kid, "missing": True}
        return {"id": kid, "name": k["name"], "value": k.get("live_value"), "target": k.get("target"),
                "unit": k.get("unit", ""), "direction": k.get("direction"), "status": kpi_status(k),
                "parent_ref": k.get("parent_ref"),
                "children": [kpi_card(c) for c in sorted(kpi_children.get(kid, []))]}

    objectives = []
    for o in objs:
        okpis = [kpi_card(kref) for kref in o.get("kpi_refs", [])]
        statuses = [kk["status"] for kk in okpis if not kk.get("missing")]
        fulfilled = bool(statuses) and all(s == "on_target" for s in statuses)
        objectives.append({
            "id": o["id"], "name": o["name"], "type": o.get("type", "annual"),
            "parent_ref": o.get("parent_ref"), "owner": o.get("owner_role"),
            "horizon": o.get("horizon"), "target": o.get("target"),
            "applies_to_levels": o.get("applies_to_levels", []),
            "kpis": okpis, "processes": sorted(obj_procs.get(o["id"], []), key=lambda x: x["id"]),
            "fulfilled": fulfilled,
            "off_target_kpis": [kk["id"] for kk in okpis if kk.get("status") == "off_target"],
        })

    # top-level KPI cards (roots of the hierarchy) with fulfilment
    kpi_roots = [kpi_card(kid) for kid, k in sorted(kpis.items()) if not k.get("parent_ref")]

    initiatives = [{"id": i["id"], "name": i["name"], "owner": i.get("owner_role"),
                    "objective_refs": i.get("objective_refs", []), "process_refs": i.get("process_refs", []),
                    "description": i.get("description", "")} for i in sorted(inits, key=lambda x: x["id"])]

    gaps = {
        "objectives_no_process": [o["id"] for o in objectives if not o["processes"]],
        "processes_no_objective": [p["id"] for p in procs if not proc_objs.get(p["id"])],
        "kpis_off_target": [kid for kid, k in kpis.items() if kpi_status(k) == "off_target"],
    }
    return {
        "enterprise": ({"name": ent["name"], "mission": ent.get("mission", ""), "vision": ent.get("vision", ""),
                        "values": ent.get("values", [])} if ent else None),
        "objectives": objectives,
        "breakthroughs": [o["id"] for o in objectives if o["type"] == "breakthrough"],
        "annuals": [o["id"] for o in objectives if o["type"] == "annual"],
        "kpi_roots": kpi_roots,
        "initiatives": initiatives,
        "gaps": gaps,
    }


def xmatrix(g: cc.Graph | None = None) -> dict:
    """Full Hoshin X-matrix (the ISOX Nexus layout), backed by the governed graph.
    Five axes — organizational goals (breakthroughs), annual objectives, change
    initiatives, metrics (the live process KPIs), and owners — with the four
    correlation corners derived from the graph's links:
      objectives ↔ goals   (annual rolls up to a breakthrough)
      initiatives ↔ objectives (an initiative advances an objective)
      initiatives ↔ metrics (an initiative moves a KPI, via a shared objective or its process)
      initiatives ↔ owners (an initiative's accountable role)
    Metrics carry live fulfilment (on/off target). Read-only, one source of truth."""
    g = g or cc.Graph()
    m = strategy(g)
    by_id = {o["id"]: o for o in m["objectives"]}
    goals = [{"id": by_id[i]["id"], "name": by_id[i]["name"]} for i in m["breakthroughs"]]
    objectives = [{"id": by_id[i]["id"], "name": by_id[i]["name"], "parent_ref": by_id[i]["parent_ref"]} for i in m["annuals"]]

    # metrics = every KPI referenced by an annual objective (the results axis), live
    metrics, seen = [], set()
    obj_kpis = {}
    for a in [by_id[i] for i in m["annuals"]]:
        obj_kpis[a["id"]] = set()
        for kk in a["kpis"]:
            obj_kpis[a["id"]].add(kk["id"])
            if kk["id"] not in seen:
                seen.add(kk["id"])
                metrics.append({"id": kk["id"], "name": kk["name"], "value": kk.get("value"),
                                "target": kk.get("target"), "unit": kk.get("unit", ""), "status": kk.get("status")})

    initiatives = m["initiatives"]
    # process → its KPIs (for the init↔metric link via a delivering process)
    proc_kpis = {p["id"]: set(p.get("kpi_refs", [])) for p in g.all("Process") if p["status"] == "active"}

    # owners axis — the roles that own objectives or initiatives
    def role_name(rid):
        r = g.get("HumanRole", rid)
        return r["name"] if r and r.get("name") else rid
    owner_ids = []
    for o in m["objectives"]:
        if o.get("owner") and o["owner"] not in owner_ids:
            owner_ids.append(o["owner"])
    for it in initiatives:
        if it.get("owner") and it["owner"] not in owner_ids:
            owner_ids.append(it["owner"])
    owners = [{"id": rid, "name": role_name(rid)} for rid in owner_ids]

    links = []
    for o in objectives:                                        # objectives ↔ goals (corner I)
        if o["parent_ref"]:
            links.append({"type": "obj_goal", "a": o["id"], "b": o["parent_ref"], "strength": "primary"})
    for it in initiatives:
        for oid in it["objective_refs"]:                        # initiatives ↔ objectives (corner A)
            if oid in by_id:
                links.append({"type": "init_obj", "a": it["id"], "b": oid, "strength": "primary"})
        init_objs = set(it["objective_refs"])
        init_proc_kpis = set()
        for pid in it.get("process_refs", []):
            init_proc_kpis |= proc_kpis.get(pid, set())
        for mm in metrics:                                      # initiatives ↔ metrics (corner C)
            via_obj = any(mm["id"] in obj_kpis.get(oid, set()) for oid in init_objs)
            via_proc = mm["id"] in init_proc_kpis
            if via_obj or via_proc:
                links.append({"type": "init_metric", "a": it["id"], "b": mm["id"],
                              "strength": "primary" if via_obj else "supporting"})
        if it.get("owner"):                                     # initiatives ↔ owners (corner D)
            links.append({"type": "init_owner", "a": it["id"], "b": it["owner"], "strength": "leading"})

    # manual cell overrides (a facilitator's explicit strength wins; 'none' forces empty)
    overrides = {(o["type"], o["a"], o["b"]): o["strength"]
                 for o in g.all("Correlation") if o.get("status") == "active"}
    merged, seen = [], set()
    for l in links:
        key = (l["type"], l["a"], l["b"])
        if key in overrides:
            seen.add(key)
            merged.append(dict(l, strength=overrides[key], manual=True))   # keep 'none' too, marked manual
        else:
            merged.append(dict(l, manual=False))
    for (t, a, b), s in overrides.items():                      # overrides on cells with no derived link
        if (t, a, b) not in seen:
            merged.append({"type": t, "a": a, "b": b, "strength": s, "manual": True})
    links = merged

    return {
        "enterprise": m["enterprise"],
        "goals": goals, "objectives": objectives, "initiatives": initiatives,
        "metrics": metrics, "owners": owners, "links": links, "gaps": m["gaps"],
    }
