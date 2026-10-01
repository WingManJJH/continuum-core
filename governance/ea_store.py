"""EA / GRC write paths — Capability, Application, Obligation, Control, Risk (D45).

Mixed into GovernanceStore, so every change goes through the same discipline as
the rest of the model: validated against the locked schema, every reference
checked, versioned (never overwritten), retired instead of deleted, appended to
the hash-chained change-control log with who / when / why (ISO 9001 §7.5), and
approvable through the review gate (one policy entity per building block).
"""
from __future__ import annotations

import copy
import json
import os
import re

import continuum_core as cc
from jsonschema import Draft202012Validator

from errors import EditError

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.normpath(os.path.join(HERE, "..", "schema"))
PACK_DIR = os.path.normpath(os.path.join(HERE, "..", "enterprise", "packs"))

EA = {
    # type: (schema file, id prefix, editable fields)
    "Capability": ("capability", "cap", {"name", "description", "level", "parent_ref", "importance", "owner",
                                         "process_refs"}),
    "Application": ("application", "app", {"name", "kind", "vendor", "owner", "lifecycle", "criticality", "data_class",
                                           "sunset_date", "description", "capability_refs", "process_refs",
                                           "task_refs", "agent_binding_refs", "obligation_refs", "risk_refs"}),
    "Obligation": ("obligation", "obl", {"pack", "source", "clause", "title", "summary", "jurisdiction",
                                         "effective_date", "process_refs"}),
    "Control": ("control", "ctl", {"name", "description", "type", "owner", "frequency", "last_tested", "last_result",
                                   "guardrail_ref", "obligation_refs", "risk_refs", "task_refs", "process_refs"}),
    "Risk": ("risk", "rsk", {"name", "description", "owner", "likelihood", "impact", "treatment", "process_refs"}),
}
DEFAULTS = {
    "Capability": {"level": 1, "parent_ref": None, "importance": "medium", "owner": "", "process_refs": []},
    "Application": {"kind": "system", "lifecycle": "active", "owner": "", "capability_refs": [], "process_refs": [],
                    "task_refs": [], "obligation_refs": [], "risk_refs": []},
    "Obligation": {"pack": "custom", "process_refs": []},
    "Control": {"type": "preventive", "frequency": "annual", "last_tested": None, "last_result": "not_tested",
                "owner": "", "obligation_refs": [], "risk_refs": [], "task_refs": [], "process_refs": []},
    "Risk": {"likelihood": 3, "impact": 3, "treatment": "mitigate", "owner": "", "process_refs": []},
}
REF_TARGET = {
    "parent_ref": "Capability", "capability_refs": "Capability", "process_refs": "Process", "task_refs": "Task",
    "agent_binding_refs": "AgentBinding", "obligation_refs": "Obligation", "risk_refs": "Risk",
    "guardrail_ref": "GuardrailPolicy",
}
LABEL = {"Capability": "capability", "Application": "application", "Obligation": "obligation",
         "Control": "control", "Risk": "risk"}


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s or "").lower()).strip("_")[:60].rstrip("_") or "item"


class EnterpriseWrites:
    """Mixin for GovernanceStore (needs graph(), _require(), EditError)."""

    _ea_validators: dict | None = None

    def _ea_validator(self, etype):
        if EnterpriseWrites._ea_validators is None:
            vs = {}
            for t, (fn, _p, _e) in EA.items():
                with open(os.path.join(SCHEMA_DIR, fn + ".schema.json")) as f:
                    vs[t] = Draft202012Validator(json.load(f))
            EnterpriseWrites._ea_validators = vs
        return EnterpriseWrites._ea_validators[etype]

    # --- shared checks -------------------------------------------------------
    def _ea_check(self, g, etype, rec):
        errs = sorted(self._ea_validator(etype).iter_errors(rec), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(f"{'.'.join(map(str, e.path)) or '(record)'}: {e.message}" for e in errs[:2]))
        for field, target in REF_TARGET.items():
            if field not in rec or rec[field] in (None, "", []):
                continue
            for ref in (rec[field] if isinstance(rec[field], list) else [rec[field]]):
                tgt = g.get(target, ref)
                if tgt is None or tgt.get("status") == "deprecated":
                    raise EditError(f"{field}: unknown or retired {target} {ref}")
        owner = rec.get("owner") or ""
        if owner.startswith("role.") and g.get("HumanRole", owner) is None:
            raise EditError(f"owner: unknown role {owner}")
        if etype == "Capability" and rec.get("parent_ref"):
            cur, steps = rec["parent_ref"], 0
            while cur and steps < 1000:
                if cur == rec["id"]:
                    raise EditError("parent_ref would make a capability its own ancestor")
                p = g.get("Capability", cur)
                cur, steps = (p or {}).get("parent_ref"), steps + 1
        if etype == "Application" and rec.get("agent_binding_refs") and rec.get("kind") != "agent":
            raise EditError("only an agent (kind=agent) can own agent bindings")

    def _ea_add(self, etype, fields: dict, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        if etype not in EA:
            raise EditError(f"unknown building block {etype}")
        fields = dict(fields or {})
        _fn, prefix, editable = EA[etype]
        unknown = set(fields) - editable - {"id"}
        if unknown:
            raise EditError(f"these fields are not editable: {sorted(unknown)}")
        name = fields.get("name") or fields.get("title") or ""
        if not str(name).strip():
            raise EditError(f"a {LABEL[etype]} needs a {'title' if etype == 'Obligation' else 'name'}")
        g = self.graph()
        explicit = fields.pop("id", None)
        rid = explicit or f"{prefix}.{_slug(name)}"
        if not rid.startswith(prefix + "."):
            raise EditError(f"a {LABEL[etype]} id starts with '{prefix}.'")
        base, n = rid, 2
        while not explicit and g.get(etype, rid) is not None:  # generated ids never collide
            rid, n = f"{base}_{n}", n + 1
        if g.get(etype, rid) is not None:
            raise EditError(f"{LABEL[etype]} {rid} already exists")
        rec = {"id": rid, **copy.deepcopy(DEFAULTS[etype]), **fields, "version": 1, "status": "active"}
        self._ea_check(g, etype, rec)
        cc.append_edit_event(etype, rid, "create", None, 1, {"kind": "human", "id": actor}, rec, reason.strip())
        return rec

    def _ea_edit(self, etype, rid, changes: dict, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        cur = g.get(etype, rid)
        if cur is None or cur.get("status") == "deprecated":
            raise EditError(f"unknown or retired {LABEL.get(etype, etype)} {rid}")
        unknown = set(changes or {}) - EA[etype][2]
        if unknown:
            raise EditError(f"these fields are not editable: {sorted(unknown)}")
        if not changes:
            raise EditError("nothing to change")
        new = copy.deepcopy(cur)
        new.update(copy.deepcopy(changes))
        new["version"] = cur["version"] + 1
        self._ea_check(g, etype, new)
        cc.append_edit_event(etype, rid, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def _ea_retire(self, etype, rid, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        cur = g.get(etype, rid)
        if cur is None or cur.get("status") == "deprecated":
            raise EditError(f"unknown or already-retired {LABEL.get(etype, etype)} {rid}")
        new = copy.deepcopy(cur)
        new["status"] = "deprecated"
        new["version"] = cur["version"] + 1
        cc.append_edit_event(etype, rid, "deprecate", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def _ea_link(self, etype, rid, field, ref, actor, reason, add=True) -> dict:
        g = self.graph()
        cur = g.get(etype, rid)
        if cur is None:
            raise EditError(f"unknown {LABEL.get(etype, etype)} {rid}")
        if field not in EA[etype][2] or not field.endswith("_refs"):
            raise EditError(f"{field} is not a link on a {LABEL[etype]}")
        refs = list(cur.get(field) or [])
        if add and ref not in refs:
            refs.append(ref)
        elif not add and ref in refs:
            refs.remove(ref)
        else:
            return cur  # already in the requested state: no event
        return self._ea_edit(etype, rid, {field: refs}, actor, reason)

    # --- public, approvable ops (one per building block, so the gate can map op -> entity)
    def add_capability(self, fields, actor, reason): return self._ea_add("Capability", fields, actor, reason)
    def edit_capability(self, id, changes, actor, reason): return self._ea_edit("Capability", id, changes, actor, reason)
    def retire_capability(self, id, actor, reason): return self._ea_retire("Capability", id, actor, reason)
    def add_application(self, fields, actor, reason): return self._ea_add("Application", fields, actor, reason)
    def edit_application(self, id, changes, actor, reason): return self._ea_edit("Application", id, changes, actor, reason)
    def retire_application(self, id, actor, reason): return self._ea_retire("Application", id, actor, reason)
    def add_obligation(self, fields, actor, reason): return self._ea_add("Obligation", fields, actor, reason)
    def edit_obligation(self, id, changes, actor, reason): return self._ea_edit("Obligation", id, changes, actor, reason)
    def retire_obligation(self, id, actor, reason): return self._ea_retire("Obligation", id, actor, reason)
    def add_control(self, fields, actor, reason): return self._ea_add("Control", fields, actor, reason)
    def edit_control(self, id, changes, actor, reason): return self._ea_edit("Control", id, changes, actor, reason)
    def retire_control(self, id, actor, reason): return self._ea_retire("Control", id, actor, reason)
    def add_risk(self, fields, actor, reason): return self._ea_add("Risk", fields, actor, reason)
    def edit_risk(self, id, changes, actor, reason): return self._ea_edit("Risk", id, changes, actor, reason)
    def retire_risk(self, id, actor, reason): return self._ea_retire("Risk", id, actor, reason)

    def link_ea(self, etype, id, field, ref, actor, reason):
        return self._ea_link(etype, id, field, ref, actor, reason, add=True)

    def unlink_ea(self, etype, id, field, ref, actor, reason):
        return self._ea_link(etype, id, field, ref, actor, reason, add=False)

    def record_control_test(self, id, result, tested_on, actor, reason):
        """Record a control test (ISO 9001 §9.1 evidence). A failure is the trigger
        for a corrective action (§10.2) — the CAPA register links back by control id."""
        if result not in ("pass", "fail"):
            raise EditError("a test result is pass or fail")
        return self._ea_edit("Control", id, {"last_result": result, "last_tested": tested_on}, actor, reason)

    # --- packs + Phase 1 bridge ----------------------------------------------
    @staticmethod
    def obligation_packs() -> dict:
        out = {}
        for fn in sorted(os.listdir(PACK_DIR)):
            if fn.endswith(".json"):
                with open(os.path.join(PACK_DIR, fn)) as f:
                    pk = json.load(f)
                out[pk["id"]] = pk
        return out

    def seed_obligation_pack(self, pack_id: str, actor: str, reason: str = "") -> dict:
        """Add every clause of a pack that is not in the model yet. Idempotent:
        existing obligations (and their mappings) are never touched."""
        reason = reason or f"seed the {pack_id} obligation pack"
        self._require(reason, actor)
        pk = self.obligation_packs().get(pack_id)
        if not pk:
            raise EditError(f"unknown obligation pack {pack_id}")
        g = self.graph()
        added = 0
        for o in pk["obligations"]:
            if g.get("Obligation", o["id"]) is not None:
                continue
            rec = {k: o[k] for k in ("id", "pack", "source", "clause", "title", "summary", "jurisdiction")}
            rec.update({"process_refs": [], "version": 1, "status": "active"})
            self._ea_check(g, "Obligation", rec)
            cc.append_edit_event("Obligation", rec["id"], "create", None, 1,
                                 {"kind": "human", "id": actor}, rec, reason.strip())
            added += 1
        return {"pack": pack_id, "added": added, "total": len(pk["obligations"])}

    def split_risk_control(self, rc_id: str, actor: str, reason: str) -> dict:
        """Turn a Phase 1 RiskControl (one risk + one control on one process) into a
        Risk and a Control that can be shared across processes and tested. The
        RiskControl is retired, not deleted, so its history stays intact."""
        self._require(reason, actor)
        g = self.graph()
        rc = g.get("RiskControl", rc_id)
        if rc is None or rc.get("status") == "deprecated":
            raise EditError(f"unknown or retired risk & control {rc_id}")
        base = _slug(rc_id.split(".", 1)[1])
        risk = self._ea_add("Risk", {"id": f"rsk.{base}", "name": rc["risk"][:200], "likelihood": rc["likelihood"],
                                     "impact": rc["impact"], "process_refs": [rc["process_ref"]]}, actor, reason)
        ctl = self._ea_add("Control", {"id": f"ctl.{base}", "name": rc["control"][:200],
                                       "type": rc.get("control_type") or "preventive",
                                       "guardrail_ref": rc.get("guardrail_ref"), "risk_refs": [risk["id"]],
                                       "process_refs": [rc["process_ref"]]}, actor, reason)
        new = copy.deepcopy(rc)
        new["status"] = "deprecated"
        new["version"] = rc["version"] + 1
        cc.append_edit_event("RiskControl", rc_id, "deprecate", rc["version"], new["version"],
                             {"kind": "human", "id": actor}, new, f"{reason.strip()} (split into {risk['id']} + {ctl['id']})")
        return {"risk": risk, "control": ctl, "retired": rc_id}


EA_OPS = {
    **{f"{verb}_{LABEL[t]}": t for t in EA for verb in ("add", "edit", "retire")},
    "record_control_test": "Control",
}
