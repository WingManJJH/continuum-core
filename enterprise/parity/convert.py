"""Studio workspace (the JS core's shape) -> continuum-core seed graph.

Used by the parity suite to run the Python engine on exactly the fixture the JS
core runs on. Ids are kept as Studio wrote them (`proc_onboarding`,
`proc_onboarding::Task_X`) because the rules never depend on id format; a
production Studio import maps them to APQC codes instead.
"""
from __future__ import annotations

import re

_SPLIT = re.compile(r"[;\n]|(?<!\d),|,(?!\d)")


def split_list(s) -> list[str]:
    return [x.strip() for x in _SPLIT.split(str(s or "")) if x.strip()]


def slug(s) -> str:
    out = re.sub(r"[^a-z0-9]+", "_", str(s or "").lower().replace("&amp;", "and")).strip("_")[:64].rstrip("_")
    return out or "item"


def decode(s) -> str:
    return (str(s or "").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'"))


def _gr(gid, g) -> dict | None:
    g = g or {}
    if not any(str(g.get(k) or "").strip() for k in ("allow", "deny", "escalateIf")):
        return None
    return {"id": gid, "allowed_actions": [slug(x) for x in split_list(g.get("allow"))],
            "forbidden_actions": [slug(x) for x in split_list(g.get("deny"))],
            "escalate_if": str(g.get("escalateIf") or ""), "version": 1, "status": "active"}


def tasks_of(p) -> list[dict]:
    out = list(p.get("tasks") or [])
    seen = {t["id"] for t in out}
    for el in (p.get("elementGovernance") or {}):
        if el not in seen:
            out.append({"id": el, "name": el})
    return out


def workspace_to_seed(ws: dict) -> dict:
    R = ws.get("registry") or {}
    seed = {k: [] for k in ("Process", "Task", "KPI", "GuardrailPolicy", "Capability", "Application",
                            "Obligation", "Control", "Risk")}
    seed["model_sig"] = "parity"
    kpis: dict[str, dict] = {}

    def kpi_ids(text):
        ids = []
        for name in split_list(text):
            kid = "kpi." + slug(name)
            kpis.setdefault(kid, {"id": kid, "name": name, "version": 1, "status": "active"})
            ids.append(kid)
        return ids

    links = {k: {} for k in ("cap", "app_p", "app_t", "obl", "rsk", "ctl_t")}
    for pid in ws.get("order") or list(ws["processes"]):
        p = ws["processes"][pid]
        L = p.get("links") or {}
        for c in L.get("capabilityIds") or []:
            links["cap"].setdefault(c, []).append(pid)
        for a in L.get("applicationIds") or []:
            links["app_p"].setdefault(a, []).append(pid)
        for o in L.get("obligationIds") or []:
            links["obl"].setdefault(o, []).append(pid)
        for r in L.get("riskIds") or []:
            links["rsk"].setdefault(r, []).append(pid)
        gr = _gr("gr." + pid, p.get("guardrail"))
        if gr:
            seed["GuardrailPolicy"].append(gr)
        status = "active" if p.get("status") in ("approved", "effective") else "draft"
        seed["Process"].append({
            "id": pid, "apqc_code": p.get("apqcCode") or "", "name": p.get("name") or pid,
            "owner_role": p.get("ownerRole") or "", "inputs": [], "outputs": [],
            "kpi_refs": kpi_ids(p.get("kpiRefs")), "risk_refs": [],
            "guardrail_ref": gr["id"] if gr else None, "maturity_score": p.get("maturityScore") or None,
            "custom": {"next_review_due": p.get("nextReviewDue") or None},
            "version": p.get("version") or 1, "status": status})
        for i, t in enumerate(tasks_of(p)):
            tid = pid + "::" + t["id"]
            eg = (p.get("elementGovernance") or {}).get(t["id"]) or {}
            EL = eg.get("links") or {}
            for a in EL.get("applicationIds") or []:
                links["app_t"].setdefault(a, []).append(tid)
            for c in EL.get("controlIds") or []:
                links["ctl_t"].setdefault(c, []).append(tid)
            tgr = _gr("gr." + tid, eg.get("guardrail"))
            if tgr:
                seed["GuardrailPolicy"].append(tgr)
            seed["Task"].append({"id": tid, "process_ref": pid, "seq": i + 1, "name": decode(t.get("name") or t["id"]),
                                 "inputs": [], "outputs": [], "data_scope": [], "performed_by": [],
                                 "kpi_refs": kpi_ids(eg.get("kpiRefs")), "guardrail_ref": tgr["id"] if tgr else None,
                                 "version": 1, "status": "active"})

    for c in (R.get("capabilities") or {}).values():
        seed["Capability"].append({"id": c["id"], "name": c.get("name"), "level": c.get("level") or 1,
                                   "parent_ref": c.get("parentId") or None, "importance": c.get("importance") or "medium",
                                   "owner": c.get("owner") or "", "process_refs": links["cap"].get(c["id"], []),
                                   "version": 1, "status": "active"})
    for a in (R.get("applications") or {}).values():
        seed["Application"].append({"id": a["id"], "name": a.get("name"), "kind": a.get("kind") or "system",
                                    "vendor": a.get("vendor") or "", "owner": a.get("owner") or "",
                                    "lifecycle": a.get("lifecycle") or "active", "criticality": a.get("criticality") or "medium",
                                    "sunset_date": a.get("sunsetDate") or None,
                                    "capability_refs": a.get("capabilityIds") or [],
                                    "process_refs": links["app_p"].get(a["id"], []),
                                    "task_refs": links["app_t"].get(a["id"], []),
                                    "obligation_refs": a.get("obligationIds") or [], "risk_refs": a.get("riskIds") or [],
                                    "version": 1, "status": "active"})
    for o in (R.get("obligations") or {}).values():
        seed["Obligation"].append({"id": o["id"], "pack": o.get("pack") or "custom", "source": o.get("source") or "",
                                   "clause": o.get("clause") or "", "title": o.get("title") or "",
                                   "summary": o.get("summary") or "", "process_refs": links["obl"].get(o["id"], []),
                                   "version": 1, "status": "active"})
    for c in (R.get("controls") or {}).values():
        seed["Control"].append({"id": c["id"], "name": c.get("name"), "type": c.get("type") or "preventive",
                                "owner": c.get("owner") or "", "frequency": c.get("frequency") or "annual",
                                "last_tested": c.get("lastTested") or None, "last_result": c.get("lastResult") or "not_tested",
                                "obligation_refs": c.get("obligationIds") or [], "risk_refs": c.get("riskIds") or [],
                                "task_refs": links["ctl_t"].get(c["id"], []), "process_refs": [],
                                "version": 1, "status": "active"})
    for r in (R.get("risks") or {}).values():
        seed["Risk"].append({"id": r["id"], "name": r.get("name"), "owner": r.get("owner") or "",
                             "likelihood": int(r.get("likelihood") or 0), "impact": int(r.get("impact") or 0),
                             "treatment": r.get("treatment") or "mitigate", "process_refs": links["rsk"].get(r["id"], []),
                             "version": 1, "status": "active"})
    seed["KPI"] = list(kpis.values())
    return seed
