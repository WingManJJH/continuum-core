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
    """Hoshin X-matrix axes + correlations, derived from the same links. Rows =
    breakthrough objectives; columns = annual objectives; right = KPIs/targets;
    bottom = initiatives; plus the delivering processes."""
    m = strategy(g)
    by_id = {o["id"]: o for o in m["objectives"]}
    breakthroughs = [by_id[i] for i in m["breakthroughs"]]
    annuals = [by_id[i] for i in m["annuals"]]
    # all KPIs referenced by annual objectives (the results axis)
    kpi_ids, kpi_map = [], {}
    for a in annuals:
        for kk in a["kpis"]:
            if kk["id"] not in kpi_map:
                kpi_map[kk["id"]] = kk
                kpi_ids.append(kk["id"])
    corr = []
    for a in annuals:                                   # annual ↔ breakthrough
        if a["parent_ref"]:
            corr.append({"row": a["parent_ref"], "col": a["id"], "kind": "obj_obj", "strong": True})
        for kk in a["kpis"]:                            # annual ↔ KPI
            corr.append({"col": a["id"], "kpi": kk["id"], "kind": "obj_kpi",
                         "strong": kk["status"] == "off_target"})
    for it in m["initiatives"]:                         # initiative ↔ annual
        for oid in it["objective_refs"]:
            corr.append({"col": oid, "init": it["id"], "kind": "init_obj", "strong": True})
    return {
        "enterprise": m["enterprise"],
        "breakthroughs": breakthroughs, "annuals": annuals,
        "kpis": [kpi_map[i] for i in kpi_ids], "initiatives": m["initiatives"],
        "correlations": corr, "gaps": m["gaps"],
    }
