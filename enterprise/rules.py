"""Ripple, Assure, Vitals and Atlas over the governed graph (D45/D46).

Python is the rules engine of record. The browser-only JS core
(`studio/core/continuum-core.js`, used by the offline Studio) implements the
same rules; `enterprise/test_parity.py` runs both on one fixture and requires
identical answers, so the two can never drift.

Result objects use the shared result contract of the JS core (camelCase keys:
`start`, `affected`, `bySeverity` …) so the canvas UI and the Studio render the
same payload.

Relationship storage is canonical — each relationship lives in exactly one
place, on the EA / GRC record, so the locked Phase 1 schemas are untouched:

    Capability.parent_ref        capability —part_of→       capability
    Capability.process_refs      process    —realizes→      capability
    Application.capability_refs  app        —serves→        capability
    Application.process_refs     app        —supports→      process
    Application.task_refs        app        —supports→      task
    Application.agent_binding_refs  (kind=agent) each binding's task is supported
    Application.obligation_refs  obligation —applies_to→    app
    Application.risk_refs        risk       —affects→       app
    Obligation.process_refs      obligation —applies_to→    process
    Risk.process_refs            risk       —affects→       process
    Control.obligation_refs      control    —satisfies→     obligation
    Control.risk_refs            control    —mitigates→     risk
    Control.task_refs            control    —implemented_in→ task
    Control.process_refs         control    —implemented_in→ process
    Task.process_ref             task       —belongs_to→    process

Phase 1 records keep working: a `RiskControl` is read as a paired risk
(id = rc id, affects its process) and control (id = rc id + "#control",
mitigates it, implemented in the process); an `AgentBinding` not owned by an
agent Application is read as an agent that supports its task.
"""
from __future__ import annotations

import os
import re
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

FREQ_DAYS = {"daily": 1, "weekly": 7, "monthly": 31, "quarterly": 92, "semiannual": 183, "annual": 366}
STATUS_LABEL = {"draft": "Draft", "active": "Active", "deprecated": "Retired"}
SEV_ORDER = {"critical": 0, "warning": 1, "info": 2}


# --------------------------------------------------------------------------- helpers
def day_num(iso) -> int | None:
    s = str(iso or "")[:10]
    try:
        return (date.fromisoformat(s) - date(1970, 1, 1)).days
    except ValueError:
        return None


def _today(today_iso) -> int:
    return day_num(today_iso) or day_num(datetime.now(timezone.utc).date().isoformat())


def _plural(n, one, many) -> str:
    return f"{n} {one if n == 1 else many}"


def _uniq(xs):
    seen, out = set(), []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out


def clause_key(c):
    out = []
    for part in str(c or "").split("."):
        try:
            out.append(float(part))
        except ValueError:
            out.append(0.0)
    return out


def _clause_cmp_key(c):
    # JS clauseCmp pads missing parts with 0 — emulate by padding to a fixed width
    k = clause_key(c)
    return k + [0.0] * (8 - len(k))


def obligation_label(o: dict) -> str:
    head = " ".join(x for x in [o.get("source", ""), ("§" + o["clause"]) if o.get("clause") else ""] if x)
    return " ".join(x for x in [head, o.get("title", "")] if x) or o["id"]


def capability_parents(caps: dict) -> dict:
    """Parent ids with cycles broken: only capabilities that are themselves on a
    cycle lose their parent, so nothing disappears from Atlas."""
    def on_cycle(cid):
        cur, steps = caps[cid].get("parent_ref"), 0
        while cur and cur in caps and steps < 1000:
            steps += 1
            if cur == cid:
                return True
            cur = caps[cur].get("parent_ref")
        return False
    out = {}
    for cid, c in caps.items():
        p = c.get("parent_ref")
        out[cid] = p if p and p in caps and not on_cycle(cid) else ""
    return out


def _active(g, etype):
    return [e for e in g.all(etype) if e.get("status", "active") != "deprecated"]


def is_blank_guardrail(gr) -> bool:
    return (not gr or (not gr.get("allowed_actions") and not gr.get("forbidden_actions")
                       and not str(gr.get("escalate_if") or "").strip()))


# --------------------------------------------------------------------------- view
class View:
    """The EA / GRC projection of one Graph: typed nodes plus canonical edges."""

    def __init__(self, g: cc.Graph):
        self.g = g
        self.procs = {p["id"]: p for p in _active(g, "Process")}
        self.tasks = {t["id"]: t for t in _active(g, "Task") if t.get("process_ref") in self.procs}
        self.caps = {c["id"]: c for c in _active(g, "Capability")}
        self.apps = {a["id"]: a for a in _active(g, "Application")}
        self.obls = {o["id"]: o for o in _active(g, "Obligation")}
        self.ctls = {c["id"]: c for c in _active(g, "Control")}
        self.risks = {r["id"]: r for r in _active(g, "Risk")}
        self.kpis = {k["id"]: k for k in g.all("KPI")}
        # Phase 1 RiskControl -> paired virtual risk + control
        for rc in _active(g, "RiskControl"):
            if rc.get("process_ref") not in self.procs:
                continue
            self.risks[rc["id"]] = {"id": rc["id"], "name": rc.get("risk", rc["id"]), "owner": "",
                                    "likelihood": rc.get("likelihood", 0), "impact": rc.get("impact", 0),
                                    "treatment": "mitigate", "process_refs": [rc["process_ref"]],
                                    "legacy": True, "status": "active"}
            self.ctls[rc["id"] + "#control"] = {
                "id": rc["id"] + "#control", "name": rc.get("control", rc["id"]),
                "type": rc.get("control_type", "preventive"), "owner": "", "frequency": "annual",
                "last_tested": None, "last_result": "not_tested", "obligation_refs": [],
                "risk_refs": [rc["id"]], "task_refs": [], "process_refs": [rc["process_ref"]],
                "legacy": True, "status": "active"}
        for p in self.procs.values():  # a process may also cite a RiskControl it is not the home of
            for r in p.get("risk_refs") or []:
                if r in self.risks and p["id"] not in self.risks[r]["process_refs"]:
                    self.risks[r]["process_refs"] = self.risks[r]["process_refs"] + [p["id"]]
        # AgentBindings owned by an agent Application vs. standalone ones
        self.bindings = {b["id"]: b for b in _active(g, "AgentBinding")}
        owned = {b for a in self.apps.values() for b in (a.get("agent_binding_refs") or [])}
        self.standalone_agents = {bid: b for bid, b in self.bindings.items()
                                  if bid not in owned and b.get("task_ref") in self.tasks}

        self.idx: dict[str, dict] = {}
        for p in self.procs.values():
            self.idx[p["id"]] = {"id": p["id"], "type": "process", "name": p["name"], "data": p}
        for t in self.tasks.values():
            self.idx[t["id"]] = {"id": t["id"], "type": "task", "name": t.get("name") or t["id"],
                                 "data": t, "procId": t["process_ref"]}
        for c in self.caps.values():
            self.idx[c["id"]] = {"id": c["id"], "type": "capability", "name": c.get("name") or c["id"], "data": c}
        for a in self.apps.values():
            self.idx[a["id"]] = {"id": a["id"], "type": "agent" if a.get("kind") == "agent" else "application",
                                 "name": a.get("name") or a["id"], "data": a}
        for b in self.standalone_agents.values():
            self.idx[b["id"]] = {"id": b["id"], "type": "agent", "name": b["id"], "data": b, "binding": True}
        for o in self.obls.values():
            self.idx[o["id"]] = {"id": o["id"], "type": "obligation", "name": obligation_label(o), "data": o}
        for c in self.ctls.values():
            self.idx[c["id"]] = {"id": c["id"], "type": "control", "name": c.get("name") or c["id"], "data": c}
        for r in self.risks.values():
            self.idx[r["id"]] = {"id": r["id"], "type": "risk", "name": r.get("name") or r["id"], "data": r}
        self.edges = self._edges()
        self.out_f: dict[str, list] = {}
        self.out_r: dict[str, list] = {}
        for e in self.edges:
            self.out_f.setdefault(e["s"], []).append(e)
            self.out_r.setdefault(e["t"], []).append(e)

    def _edges(self) -> list[dict]:
        out, seen = [], set()

        def e(s, t, typ):
            if s and t and s in self.idx and t in self.idx and (s, t, typ) not in seen:
                seen.add((s, t, typ))
                out.append({"s": s, "t": t, "type": typ})

        for t in self.tasks.values():
            e(t["id"], t["process_ref"], "belongs_to")
        parents = capability_parents(self.caps)
        for c in self.caps.values():
            for p in c.get("process_refs") or []:
                e(p, c["id"], "realizes")
        for a in self.apps.values():
            for c in a.get("capability_refs") or []:
                e(a["id"], c, "serves")
            for p in a.get("process_refs") or []:
                e(a["id"], p, "supports")
            for t in a.get("task_refs") or []:
                e(a["id"], t, "supports")
            for b in a.get("agent_binding_refs") or []:
                if b in self.bindings:
                    e(a["id"], self.bindings[b].get("task_ref"), "supports")
            for o in a.get("obligation_refs") or []:
                e(o, a["id"], "applies_to")
            for r in a.get("risk_refs") or []:
                e(r, a["id"], "affects")
        for b in self.standalone_agents.values():
            e(b["id"], b["task_ref"], "supports")
        for o in self.obls.values():
            for p in o.get("process_refs") or []:
                e(o["id"], p, "applies_to")
        for r in self.risks.values():
            for p in r.get("process_refs") or []:
                e(r["id"], p, "affects")
        for c in self.ctls.values():
            for o in c.get("obligation_refs") or []:
                e(c["id"], o, "satisfies")
            for r in c.get("risk_refs") or []:
                e(c["id"], r, "mitigates")
            for t in c.get("task_refs") or []:
                e(c["id"], t, "implemented_in")
            for p in c.get("process_refs") or []:
                e(c["id"], p, "implemented_in")
        for c in self.caps.values():
            if parents[c["id"]]:
                e(c["id"], parents[c["id"]], "part_of")
        return out

    # guardrail as the agent sees it (Phase 1 inheritance: task override wins)
    def guardrail_for(self, node_id):
        if node_id in self.tasks:
            gr, pinned = self.g.effective_guardrail(node_id)
            return gr, pinned, ("task" if self.tasks[node_id].get("guardrail_ref") else "process")
        p = self.procs.get(node_id)
        if p and p.get("guardrail_ref"):
            gr = self.g.get("GuardrailPolicy", p["guardrail_ref"])
            if gr:
                return gr, f"{gr['id']}.v{gr['version']}", "process"
        return None, None, "process"

    def kpi_names(self, refs) -> list[str]:
        return [self.kpis[k]["name"] if k in self.kpis else k for k in (refs or [])]


def view(g: cc.Graph | None = None) -> View:
    return View(g or cc.Graph())


# --------------------------------------------------------------------------- Ripple
VERB = {
    "supports>": "supports", "belongs_to>": "is a step in", "realizes>": "realizes", "serves>": "serves",
    "part_of>": "rolls up to", "implemented_in<": "hosts control", "implemented_in>": "runs in",
    "satisfies>": "satisfies", "satisfies<": "is satisfied by", "mitigates>": "mitigates",
    "applies_to>": "applies to", "affects>": "affects", "realizes<": "is realized by",
    "serves<": "is served by", "part_of<": "includes", "supports<": "is supported by", "belongs_to<": "contains",
}


def ripple(v: View, start_id: str, max_depth: int = 6) -> dict:
    """What a change to `start_id` touches. Capabilities read upstream (what they
    depend on); everything else reads downstream impact. applies_to / affects are
    followed only from the start node, so an obligation reached through a control
    does not fan out to every process it applies to."""
    idx = v.idx
    start = idx.get(start_id)
    if not start:
        return {"start": None, "affected": [], "kpis": [], "guardrails": [], "counts": {},
                "summary": "Unknown item."}
    upstream = start["type"] == "capability"
    via_obligation: set[str] = set()

    def steps(node, is_start):
        res = []

        def fwd(types):
            for x in v.out_f.get(node["id"], []):
                if x["type"] in types:
                    res.append((x["t"], x["type"] + ">"))

        def rev(types):
            for x in v.out_r.get(node["id"], []):
                if x["type"] in types:
                    res.append((x["s"], x["type"] + "<"))

        if upstream:
            rev(["realizes", "serves", "part_of"])
            if node["type"] == "process":
                rev(["belongs_to", "supports"])
            if node["type"] == "task":
                rev(["supports"])
            return res
        fwd(["supports", "belongs_to", "realizes", "serves", "part_of", "satisfies", "mitigates"])
        rev(["implemented_in"])
        if is_start:
            fwd(["applies_to", "affects"])
            if node["type"] == "control":
                fwd(["implemented_in"])
            if node["type"] == "obligation":
                rev(["satisfies"])
            if node["type"] == "process":
                rev(["belongs_to"])
        if node["type"] == "control" and node["id"] in via_obligation:
            fwd(["implemented_in"])
        return res

    seen = {start_id: {"depth": 0, "parent": None, "key": None}}
    queue = [start_id]
    while queue:
        nid = queue.pop(0)
        meta = seen[nid]
        if meta["depth"] >= max_depth:
            continue
        for to, key in steps(idx[nid], nid == start_id):
            if to in seen or to not in idx:
                continue
            seen[to] = {"depth": meta["depth"] + 1, "parent": nid, "key": key}
            if nid == start_id and start["type"] == "obligation" and idx[to]["type"] == "control":
                via_obligation.add(to)
            queue.append(to)

    def path_to(nid):
        p, cur = [], nid
        while cur and cur in seen and seen[cur]["parent"]:
            p.insert(0, {"id": cur, "name": idx[cur]["name"], "type": idx[cur]["type"],
                         "verb": VERB.get(seen[cur]["key"], seen[cur]["key"])})
            cur = seen[cur]["parent"]
        return p

    affected = [{"id": nid, "type": idx[nid]["type"], "name": idx[nid]["name"], "depth": seen[nid]["depth"],
                 "path": path_to(nid), "procId": idx[nid].get("procId")}
                for nid in seen if nid != start_id]

    if not upstream:  # agents bound to impacted tasks/processes: their context changes underneath them
        hit = {a["id"] for a in affected} | {start_id}
        scan = list(affected)
        if start["type"] in ("task", "process"):
            scan.insert(0, {"id": start_id, "type": start["type"], "depth": 0, "path": []})
        for a in scan:
            if a["type"] not in ("task", "process"):
                continue
            for x in v.out_r.get(a["id"], []):
                if x["type"] != "supports" or x["s"] in hit:
                    continue
                n = idx.get(x["s"])
                if not n or n["type"] != "agent":
                    continue
                hit.add(x["s"])
                affected.append({"id": x["s"], "type": "agent", "name": n["name"], "depth": a["depth"] + 1,
                                 "path": a["path"] + [{"id": x["s"], "name": n["name"], "type": "agent",
                                                       "verb": "is bound to it"}],
                                 "procId": None, "bindingOnly": True})

    proc_ids = _uniq([a["id"] for a in affected if a["type"] == "process"]
                     + ([start_id] if start["type"] == "process" else []))
    task_hits = [a["id"] for a in affected if a["type"] == "task"] + ([start_id] if start["type"] == "task" else [])
    kpis, guardrails = [], []
    if not upstream:
        for pid in proc_ids:
            p = v.procs[pid]
            for k in v.kpi_names(p.get("kpi_refs")):
                kpis.append({"name": k, "procId": pid, "procName": p["name"]})
        for tid in task_hits:
            t = v.tasks[tid]
            p = v.procs[t["process_ref"]]
            for k in v.kpi_names(t.get("kpi_refs")):
                kpis.append({"name": k, "procId": p["id"], "procName": p["name"], "task": idx[tid]["name"]})
        for tid in task_hits:
            agents = [idx[x["s"]]["name"] for x in v.out_r.get(tid, [])
                      if x["type"] == "supports" and idx.get(x["s"], {}).get("type") == "agent"]
            if not agents:
                continue
            gr, pinned, source = v.guardrail_for(tid)
            p = v.procs[v.tasks[tid]["process_ref"]]
            guardrails.append({"taskId": tid, "task": idx[tid]["name"], "procName": p["name"], "agents": agents,
                               "source": source, "version": pinned, "blank": is_blank_guardrail(gr)})

    counts: dict[str, int] = {}
    for a in affected:
        counts[a["type"]] = counts.get(a["type"], 0) + 1
    st = {"id": start_id, "type": start["type"], "name": start["name"]}
    return {"start": st, "mode": "upstream" if upstream else "impact", "affected": affected, "kpis": kpis,
            "guardrails": guardrails, "counts": counts, "summary": _summarize(st, counts, kpis, upstream)}


def _summarize(start, c, kpis, upstream) -> str:
    if upstream:
        parts = []
        if c.get("process"):
            parts.append(_plural(c["process"], "process", "processes"))
        if c.get("application"):
            parts.append(_plural(c["application"], "system", "systems"))
        if c.get("agent"):
            parts.append(_plural(c["agent"], "agent", "agents"))
        if c.get("capability"):
            parts.append(_plural(c["capability"], "sub-capability", "sub-capabilities"))
        return (start["name"] + " depends on " + ", ".join(parts) + ".") if parts else \
            start["name"] + " has nothing mapped to it yet."
    bits = []
    for key, one, many in (("task", "task", "tasks"), ("process", "process", "processes"),
                           ("capability", "capability", "capabilities")):
        if c.get(key):
            bits.append(_plural(c[key], one, many))
    if kpis:
        bits.append(_plural(len(kpis), "KPI", "KPIs"))
    for key, one, many in (("control", "control", "controls"), ("obligation", "obligation", "obligations"),
                           ("risk", "risk", "risks"), ("application", "system", "systems"),
                           ("agent", "agent", "agents")):
        if c.get(key):
            bits.append(_plural(c[key], one, many))
    if not bits:
        return "Nothing else in the model depends on " + start["name"] + "."
    last = bits.pop()
    return "A change to " + start["name"] + " reaches " + ((", ".join(bits) + " and " + last) if bits else last) + "."


# --------------------------------------------------------------------------- Assure
def control_in_date(c: dict, today: int) -> bool:
    d = day_num(c.get("last_tested"))
    if d is None or d > today:  # a future test date is not evidence
        return False
    return today - d <= FREQ_DAYS.get(c.get("frequency"), 366)


def process_approved(p: dict, today: int) -> bool:
    """In continuum-core a process is released when `active` (changes to it are
    governed by the approval policy); a lapsed review date withdraws it as evidence."""
    if p.get("status") != "active":
        return False
    due = day_num((p.get("custom") or {}).get("next_review_due"))
    return due is None or due >= today


def assure(v: View, today_iso: str | None = None) -> dict:
    """Clause-by-clause evidence matrix for every obligation pack (ISO 9001 §9.2 audit prep)."""
    today = _today(today_iso)
    by_obl: dict[str, dict] = {}

    def row(o):
        return by_obl.setdefault(o, {"processes": [], "applications": [], "controls": []})

    for o in v.obls.values():
        for pid in o.get("process_refs") or []:
            if pid in v.procs:
                row(o["id"])["processes"].append(v.procs[pid])
    for a in v.apps.values():
        for o in a.get("obligation_refs") or []:
            row(o)["applications"].append(a)
    for c in v.ctls.values():
        for o in c.get("obligation_refs") or []:
            row(o)["controls"].append(c)

    packs: dict[str, dict] = {}
    for o in v.obls.values():
        key = o.get("source") or "Custom"
        pk = packs.setdefault(key, {"source": key, "pack": o.get("pack") or "custom", "rows": [],
                                    "covered": 0, "partial": 0, "gap": 0})
        r = by_obl.get(o["id"], {"processes": [], "applications": [], "controls": []})
        evidence = []
        for p in r["processes"]:
            due = (p.get("custom") or {}).get("next_review_due")
            evidence.append({"kind": "process", "id": p["id"],
                             "label": f"{p['name']} v{p.get('version', 1)} · {STATUS_LABEL.get(p.get('status'), p.get('status'))}"
                                      + (f" · review due {due}" if due else ""),
                             "good": process_approved(p, today)})
        for c in r["controls"]:
            good = c.get("last_result") == "pass" and control_in_date(c, today)
            evidence.append({"kind": "control", "id": c["id"],
                             "label": c["name"] + " · " + (f"tested {c['last_tested']} · {c.get('last_result')}"
                                                          if c.get("last_tested") else "never tested"),
                             "good": good, "failing": c.get("last_result") == "fail"})
        linked = len(r["processes"]) + len(r["applications"]) + len(r["controls"])
        if not linked:
            status, reason = "gap", "No process, system or control is mapped to this clause."
        elif any(e.get("failing") for e in evidence):
            status, reason = "partial", "A mapped control failed its last test."
        elif any(e["good"] for e in evidence):
            status, reason = "covered", "Approved process or in-date passing control on record."
        else:
            status, reason = "partial", "Mapped, but no approved process or in-date passing control yet."
        pk[status] += 1
        pk["rows"].append({"obligation": o,
                           "processes": [{"id": p["id"], "name": p["name"]} for p in r["processes"]],
                           "applications": [{"id": a["id"], "name": a["name"]} for a in r["applications"]],
                           "controls": [{"id": c["id"], "name": c["name"]} for c in r["controls"]],
                           "evidence": evidence, "status": status, "reason": reason})
    out = list(packs.values())
    for pk in out:
        pk["total"] = len(pk["rows"])
        pk["coverage"] = round(pk["covered"] / pk["total"] * 100) if pk["total"] else 0
        pk["rows"].sort(key=lambda r: _clause_cmp_key(r["obligation"].get("clause")))
    out.sort(key=lambda pk: pk["source"])
    return {"packs": out}


# --------------------------------------------------------------------------- Vitals
def _mk(severity, rule, ref, message, hint):
    return {"severity": severity, "rule": rule, "nodeId": ref[0], "nodeType": ref[1], "name": ref[2],
            "message": message, "hint": hint}


def vitals(v: View, today_iso: str | None = None) -> dict:
    """Model health: every rule is a check; the score is the share that pass."""
    today = _today(today_iso)
    st = {"checks": 0, "passed": 0}
    findings = []

    def check(ok, f):
        st["checks"] += 1
        if ok:
            st["passed"] += 1
        else:
            findings.append(f)

    def into(nid, typ):
        return [x for x in v.out_r.get(nid, []) if x["type"] == typ]

    def from_(nid, typ):
        return [x for x in v.out_f.get(nid, []) if x["type"] == typ]

    for p in v.procs.values():
        ref = (p["id"], "process", p["name"])
        check(bool(str(p.get("owner_role") or "").strip()), _mk("critical", "process-owner", ref,
              "Process has no accountable owner.", "Set a process owner — ISO 9001 §4.4 and §5.3 expect one per process."))
        check(bool(p.get("apqc_code")), _mk("info", "process-apqc", ref, "Process is not classified against APQC.",
              "Pick an APQC category so KPIs and guardrails share a join key."))
        due_s = (p.get("custom") or {}).get("next_review_due")
        due = day_num(due_s)
        if due is not None:
            check(due >= today, _mk("warning", "process-review-overdue", ref, f"Review was due {due_s}.",
                  "Review the process and record the new review date (ISO 9001 §7.5)."))
        else:
            check(False, _mk("info", "process-review-unset", ref, "No next-review date is set.",
                  "Set a review cadence so the record cannot silently go stale."))
        check(len(from_(p["id"], "realizes")) > 0,
              _mk("warning", "process-capability", ref, "Process is not linked to any capability.",
                  "Link the capability it realizes so it appears in Atlas and strategy roll-ups."))
        check(len(p.get("kpi_refs") or []) > 0, _mk("info", "process-kpi", ref, "Process has no KPI.",
              "Add at least one measure (ISO 9001 §9.1)."))

    for a in v.apps.values():
        is_agent = a.get("kind") == "agent"
        ref = (a["id"], "agent" if is_agent else "application", a["name"])
        check(bool(str(a.get("owner") or "").strip()), _mk("critical" if is_agent else "warning", "app-owner", ref,
              ("Agent" if is_agent else "System") + " has no owner.", "Assign an accountable owner."))
        uses = from_(a["id"], "supports")
        n = _plural(len(uses), "process or task", "processes or tasks")
        if a.get("lifecycle") == "retired":
            check(not uses, _mk("critical", "app-retired-in-use", ref, f"Retired, but still supports {n}.",
                  "Open Ripple to see what breaks, then move those steps to an active system."))
        elif a.get("lifecycle") == "sunset":
            when = f" on {a['sunset_date']}" if a.get("sunset_date") else ""
            check(not uses, _mk("warning", "app-sunset-in-use", ref, f"Sunsetting{when}, but still supports {n}.",
                  "Plan the migration before the sunset date; Ripple shows the full impact."))
        if not is_agent and a.get("lifecycle") == "active":
            check(len(a.get("capability_refs") or []) > 0, _mk("info", "app-capability", ref,
                  "Active system serves no capability.", "Map it in Atlas, or confirm it is a retirement candidate."))
        if is_agent:
            check(len(uses) > 0, _mk("info", "agent-unbound", ref, "Agent is not bound to any task.",
                  "Bind it to the task it performs so its guardrail applies."))
            for u in uses:
                gr, _pin, _src = v.guardrail_for(u["t"])
                check(not is_blank_guardrail(gr), _mk("critical", "agent-unguarded", ref,
                      "Bound to “" + v.idx[u["t"]]["name"] + "” with no guardrail.",
                      "Add allow / deny / escalate rules on the task or its process before the agent acts."))

    for c in v.ctls.values():
        if c.get("legacy"):
            continue  # a Phase 1 RiskControl carries no test record to check
        ref = (c["id"], "control", c["name"])
        check(c.get("last_result") != "fail", _mk("critical", "control-failed", ref, "Failed its last test.",
              "Raise a corrective action (ISO 9001 §10.2) and re-test."))
        if not c.get("last_tested"):
            check(False, _mk("warning", "control-untested", ref, "Has never been tested.", "Test it and record the result."))
        else:
            check(control_in_date(c, today), _mk("warning", "control-test-overdue", ref,
                  f"Test is overdue ({c.get('frequency') or 'annual'}, last {c['last_tested']}).",
                  "Re-test and record the result."))
        check(len(c.get("obligation_refs") or []) + len(c.get("risk_refs") or []) > 0,
              _mk("info", "control-orphan", ref, "Satisfies no obligation and mitigates no risk.", "Link it, or retire it."))

    for r in v.risks.values():
        ref = (r["id"], "risk", r["name"])
        score = int(r.get("likelihood") or 0) * int(r.get("impact") or 0)
        if r.get("treatment") != "accept":
            check(len(into(r["id"], "mitigates")) > 0, _mk("critical" if score >= 15 else "warning", "risk-unmitigated",
                  ref, f"Risk score {score} with no mitigating control.",
                  "Link a control, or record the treatment as accepted."))

    parents = capability_parents(v.caps)
    for c in v.caps.values():
        if any(parents[x] == c["id"] for x in v.caps):
            continue
        ref = (c["id"], "capability", c["name"])
        check(len(into(c["id"], "realizes")) > 0, _mk("info", "capability-unrealized", ref,
              "No process realizes this capability.", "Link the process that delivers it, or mark it as planned."))

    for pk in assure(v, today_iso)["packs"]:
        guidance = pk["pack"] == "iso9004"
        check(pk["gap"] == 0, _mk("info" if guidance else "warning", "assure-gaps", (None, "pack", pk["source"]),
              f"{pk['gap']} of {pk['total']} {pk['source']} clauses have nothing mapped.",
              "Open Assure and map processes or controls to the open clauses."))

    findings.sort(key=lambda f: (SEV_ORDER[f["severity"]], f["name"]))
    by_sev = {"critical": 0, "warning": 0, "info": 0}
    for f in findings:
        by_sev[f["severity"]] += 1
    checks, passed = st["checks"], st["passed"]
    return {"score": round(passed / checks * 100) if checks else 100, "checks": checks, "passed": passed,
            "bySeverity": by_sev, "findings": findings}


# --------------------------------------------------------------------------- Atlas
def atlas(v: View) -> list[dict]:
    """Capability map: the L1–L5 tree with the processes that realize and the
    systems that serve each capability, roll-up maturity and overlap."""
    parents = capability_parents(v.caps)
    children: dict[str, list] = {}
    for c in v.caps.values():
        children.setdefault(parents[c["id"]] or "", []).append(c)
    for k in children:
        children[k].sort(key=lambda c: c.get("name", ""))
    realizes: dict[str, list] = {}
    serves: dict[str, list] = {}
    for c in v.caps.values():
        for pid in c.get("process_refs") or []:
            if pid in v.procs:
                realizes.setdefault(c["id"], []).append(v.procs[pid])
    for a in v.apps.values():
        for cid in a.get("capability_refs") or []:
            serves.setdefault(cid, []).append(a)

    def uniq_by(xs):
        seen, out = set(), []
        for x in xs:
            if x["id"] not in seen:
                seen.add(x["id"])
                out.append(x)
        return out

    def build(c, depth):
        kids = [build(k, depth + 1) for k in children.get(c["id"], [])]
        procs = list(realizes.get(c["id"], []))
        apps = list(serves.get(c["id"], []))
        for k in kids:
            procs += k["allProcesses"]
            apps += k["allApps"]
        procs, apps = uniq_by(procs), uniq_by(apps)
        scored = [p for p in procs if p.get("maturity_score")]
        direct = [a for a in serves.get(c["id"], []) if a.get("kind") != "agent" and a.get("lifecycle") == "active"]
        return {
            "id": c["id"], "name": c["name"], "level": c.get("level") or depth,
            "importance": c.get("importance") or "medium", "owner": c.get("owner") or "", "depth": depth,
            "processes": [{"id": p["id"], "name": p["name"], "maturity": p.get("maturity_score") or 0}
                          for p in realizes.get(c["id"], [])],
            "applications": [{"id": a["id"], "name": a["name"], "kind": a.get("kind"), "lifecycle": a.get("lifecycle")}
                             for a in serves.get(c["id"], [])],
            "allProcesses": procs, "allApps": apps,
            "maturity": (round(sum(p["maturity_score"] for p in scored) / len(scored) * 10) / 10) if scored else None,
            "overlap": [a["name"] for a in direct] if len(direct) >= 2 else None,
            "children": kids,
        }

    return [build(c, 1) for c in children.get("", [])]


def atlas_public(tree):
    """Atlas without the roll-up working lists (what the API returns)."""
    return [{k: (atlas_public(v) if k == "children" else v) for k, v in n.items()
             if k not in ("allProcesses", "allApps")} for n in tree]


def graph_export(v: View) -> dict:
    return {"schema": "continuum.graph.v1",
            "nodes": [{"id": n["id"], "type": n["type"], "name": n["name"], "procId": n.get("procId")}
                      for n in v.idx.values()],
            "edges": v.edges}


_SLUG = re.compile(r"[^a-z0-9]+")


def slug(s: str) -> str:
    return _SLUG.sub("_", str(s or "").lower().replace("&amp;", "and")).strip("_")[:64].rstrip("_") or "item"
