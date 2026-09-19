"""
Generic model importer — normalized rows -> a schema-valid Continuum model seed.

Every source (Microsoft BPC, SYSPRO, Sunrise, a hand-made CSV) becomes a thin
adapter that produces NORMALIZED items; this module turns them into an isolated
model (data/models/<slug>/), so the whole stack can fold and toggle it. One place
owns the invariants — id scheme, ancestor synthesis, the shared default guardrail
and owner role — so every importer inherits them.

A normalized item:
  {
    "code":  "OC.5.10.100",   # a Continuum id: 2-letter prefix + numeric path
    "name":  "Define order policies",
    "level": 4,               # optional; inferred from the code if omitted
    "kind":  "group"|"process",# optional; inferred (a code with descendants = group)
    "parent":"OC.5.10",       # optional; derived from the code if omitted
    "description": "...",     # optional; kept in custom on processes
    "custom": { ... },        # optional free-form master data
  }
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

DEFAULT_GUARDRAIL = "gr.DEFAULT"
DEFAULT_ROLE = "role.unassigned"
CODE_RE = re.compile(r"^[A-Z]{2}(\.[0-9]+)*$")   # ProcessGroup id shape; processes are the same


def _parent(code: str):
    return code.rsplit(".", 1)[0] if "." in code else None


def _clean(s: str) -> str:
    """Strip markup/entities/whitespace so a description enters the model as text."""
    s = re.sub(r"<[^>]+>", " ", str(s or ""))
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return re.sub(r"\s+", " ", s).strip()


def build_model_seed(items: list[dict], model_name: str, sig: str = "model") -> dict:
    """Normalized items -> a schema-valid seed dict. Codes must be alpha-prefixed
    (^[A-Z]{2}(\\.[0-9]+)*$); a code that any other code descends from is a group,
    the rest are processes. Missing ancestor groups are synthesized so every
    parent_ref resolves; duplicate process codes are suffixed."""
    codes = [it["code"] for it in items]
    bad = [c for c in codes if not CODE_RE.match(c or "")]
    if bad:
        raise ValueError(f"codes must be alpha-prefixed like AB.1.2 — bad: {bad[:3]}")
    has_child = set()
    for c in codes:
        p = _parent(c)
        while p:
            has_child.add(p)
            p = _parent(p)

    groups: dict[str, dict] = {}
    procs: dict[str, dict] = {}
    seen: set[str] = set()

    def ensure_group(code, name=None, desc="", custom=None, level=None):
        if not code or code in groups:
            return
        groups[code] = {"id": code, "name": name or code, "level": level or min(code.count(".") + 1, 5),
                        "parent_ref": _parent(code), "owner_role": None, "objective_refs": [],
                        "description": desc, "custom": custom or {"implied": True},
                        "version": 1, "status": "active"}
        ensure_group(_parent(code))

    for it in items:
        code = it["code"]
        name = _clean(it.get("name")) or code
        desc = _clean(it.get("description"))[:600]
        custom = dict(it.get("custom") or {})
        kind = it.get("kind") or ("group" if code in has_child else "process")
        if kind == "group":
            groups.pop(code, None)  # explicit row wins over any synthesized stub
            ensure_group(code, name, desc, custom or None, it.get("level"))
        else:
            pid, n = code, 2
            while pid in seen:
                pid = f"{code}.{n}"; n += 1
            seen.add(pid)
            if desc:
                custom = dict(custom, description=desc)
            procs[pid] = {"id": pid, "apqc_code": pid, "name": name, "owner_role": DEFAULT_ROLE,
                          "inputs": [], "outputs": [], "interfaces": {}, "kpi_refs": [], "risk_refs": [],
                          "guardrail_ref": DEFAULT_GUARDRAIL, "parent_ref": _parent(code),
                          "next_process_refs": [], "custom": custom, "maturity_score": None,
                          "version": 1, "status": "active"}
            ensure_group(_parent(code))
    for c in list(groups):
        ensure_group(_parent(c))

    role = {"id": DEFAULT_ROLE, "name": "Unassigned owner", "raci": {}, "skills": [],
            "version": 1, "status": "active"}
    guard = {"id": DEFAULT_GUARDRAIL, "attaches_to": {"kind": "process", "ref": "default"},
             "allowed_actions": [], "forbidden_actions": [], "escalate_if": "always",
             "data_scope": [], "rate_limit": None, "escalation_path": DEFAULT_ROLE,
             "audit_requirement": "timestamp_outcome", "version": 1, "status": "active"}
    return {"_note": f"Imported model — {model_name}", "model_sig": sig,
            "StrategicObjective": [], "Enterprise": [], "Initiative": [], "Correlation": [],
            "KPI": [], "Process": list(procs.values()), "Task": [],
            "HumanRole": [role], "AgentBinding": [], "GuardrailPolicy": [guard],
            "RiskControl": [], "ProcessGroup": list(groups.values()),
            "Gateway": [], "SequenceFlow": [], "Event": []}


def write_model(slug: str, name: str, seed: dict, source: str, description: str) -> str:
    base = cc.model_base(slug)
    os.makedirs(base, exist_ok=True)
    with open(os.path.join(base, "seed.json"), "w") as f:
        json.dump(seed, f, indent=1)
    with open(os.path.join(base, "model.json"), "w") as f:
        json.dump({"name": name, "source": source, "description": description}, f, indent=1)
    return base


def read_csv(path: str) -> list[dict]:
    """Read a normalized export: columns code,name[,level,kind,parent,description].
    The universal path — export any source to this and it imports."""
    items = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            if not row.get("code"):
                continue
            it = {"code": row["code"], "name": row.get("name", "")}
            if row.get("level"):
                it["level"] = int(row["level"])
            if row.get("kind"):
                it["kind"] = row["kind"]
            if row.get("parent"):
                it["parent"] = row["parent"]
            if row.get("description"):
                it["description"] = row["description"]
            items.append(it)
    return items
