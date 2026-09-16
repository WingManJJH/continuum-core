"""
Governance store — Phase 2 write layer (Core Model §09 Phase 2, §04, §10).

Turns "guardrails are data, not code" into a real edit path: a process owner
changes a Guardrail Policy, it is validated, versioned, and committed to the
change-control log — no deploy. The MCP server reads the folded result, so the
edit is live for agents the moment it is saved (one source of truth).

Every edit:
  - is validated against the LOCKED guardrail schema (an invalid edit is refused,
    not shipped),
  - lints the escalate_if expression through the same evaluator the Enforcement
    Point uses (a bad condition can't reach production),
  - bumps the version (never overwrites),
  - records who / when / why in the review block (ISO 9001 §7.5),
  - appends one immutable event to data/edits.log.jsonl.

Read-only concerns (process list, history, audit) are also here so the web app
(app.py) stays a thin transport over this module.
"""
from __future__ import annotations

import copy
import json
import os
import re
import sys
from datetime import datetime, timezone

# make the sibling mcp_server package importable
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

from jsonschema import Draft202012Validator  # noqa: E402

SCHEMA_DIR = os.path.normpath(os.path.join(HERE, "..", "schema"))
EDITABLE_FIELDS = [
    "allowed_actions", "forbidden_actions", "escalate_if", "data_scope",
    "rate_limit", "escalation_path", "audit_requirement",
]
EDITABLE_TASK_FIELDS = [
    "name", "seq", "performed_by", "inputs", "outputs", "data_scope",
    "kpi_refs", "guardrail_ref", "subprocess_ref",
]
EDITABLE_ROLE_FIELDS = ["name", "raci", "skills"]


class EditError(ValueError):
    """A rejected edit — the reason is safe to show the owner in the UI."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class GovernanceStore:
    def __init__(self):
        with open(os.path.join(SCHEMA_DIR, "guardrail-policy.schema.json")) as f:
            self._gr_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "task.schema.json")) as f:
            self._task_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "process.schema.json")) as f:
            self._process_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "agent-binding.schema.json")) as f:
            self._binding_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "gateway.schema.json")) as f:
            self._gateway_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "sequence-flow.schema.json")) as f:
            self._flow_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "event.schema.json")) as f:
            self._event_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(SCHEMA_DIR, "human-role.schema.json")) as f:
            self._role_validator = Draft202012Validator(json.load(f))
        with open(os.path.join(HERE, "..", "guardrail-template", "default-guardrail-policy.json")) as f:
            self._default_gr = json.load(f)

    def graph(self) -> cc.Graph:
        return cc.Graph()  # folds seed + edit log every load

    # --- reads -------------------------------------------------------------
    def process_list(self) -> list[dict]:
        g = self.graph()
        out = []
        for p in sorted(g.all("Process"), key=lambda x: x["id"]):
            gr = g.get("GuardrailPolicy", p.get("guardrail_ref"))
            risks = [g.get("RiskControl", r) for r in p.get("risk_refs", [])]
            out.append({
                "id": p["id"], "name": p["name"], "owner_role": p["owner_role"],
                "status": p["status"],
                "guardrail": None if not gr else {
                    "id": gr["id"], "version": gr["version"],
                    "allowed": len(gr["allowed_actions"]),
                    "forbidden": len(gr["forbidden_actions"]),
                    "escalate_if": gr["escalate_if"],
                },
                "task_overrides": sorted(
                    t["guardrail_ref"] for t in g.all("Task")
                    if t["process_ref"] == p["id"] and t.get("guardrail_ref")
                ),
                "risks": [{"id": r["id"], "risk": r["risk"], "control": r["control"],
                           "likelihood": r["likelihood"], "impact": r["impact"]}
                          for r in risks if r],
            })
        return out

    def guardrail(self, gr_id: str) -> dict:
        gr = self.graph().get("GuardrailPolicy", gr_id)
        if gr is None:
            raise EditError(f"unknown guardrail {gr_id}")
        return gr

    def linked_risks(self, gr_id: str) -> list[dict]:
        g = self.graph()
        return [r for r in g.all("RiskControl") if r.get("guardrail_ref") == gr_id]

    def history(self, gr_id: str) -> list[dict]:
        """Version timeline for one guardrail: the seed baseline plus every edit,
        newest first, each with actor / timestamp / reason."""
        rows = []
        base = cc.Graph(apply_edits=False).get("GuardrailPolicy", gr_id)
        if base:
            rev = base.get("review", {})
            rows.append({"version": base["version"], "ts": rev.get("reviewed_at"),
                         "actor": rev.get("reviewed_by", "seed"),
                         "reason": rev.get("note", "seed baseline"), "source": "baseline"})
        for ev in self._read_log(cc.EDITS_LOG):
            if ev["entity_type"] == "GuardrailPolicy" and ev["entity_id"] == gr_id:
                rows.append({"version": ev["to_version"], "ts": ev["ts"],
                             "actor": ev["actor"]["id"], "reason": ev["reason"],
                             "source": "edit"})
        return sorted(rows, key=lambda r: r["version"], reverse=True)

    def audit(self, limit: int = 200) -> list[dict]:
        """The unified ISO 9001 §7.5 trail: change-control events (guardrail edits)
        and agent-action events, one timeline."""
        rows = []
        for ev in self._read_log(cc.EDITS_LOG):
            rows.append({"ts": ev["ts"], "kind": "change_control",
                         "entity": f"{ev['entity_type']} {ev['entity_id']}",
                         "detail": f"v{ev.get('from_version')}→v{ev['to_version']}: {ev['reason']}",
                         "actor": ev["actor"]["id"], "actor_kind": ev["actor"]["kind"]})
        for ev in self._read_log(cc.EVENTS_LOG):
            p = ev.get("payload", {})
            rows.append({"ts": ev["ts"], "kind": "agent_action",
                         "entity": f"{ev['entity_type']} {ev['entity_id']}",
                         "detail": f"{p.get('action')} → {p.get('outcome')} "
                                   f"(cited {p.get('guardrail_version')})",
                         "actor": ev["actor"]["id"], "actor_kind": ev["actor"]["kind"]})
        return sorted(rows, key=lambda r: r["ts"], reverse=True)[:limit]

    def integrity(self) -> dict:
        """Tamper-evidence status of the audit logs (ISO 9001 §7.5) for the UI."""
        return cc.verify_audit()

    # --- the write path ----------------------------------------------------
    def edit_guardrail(self, gr_id: str, changes: dict, actor: str,
                       reason: str, reviewer: str) -> dict:
        if not reason or not reason.strip():
            raise EditError("a change reason is required (ISO 9001 §7.5 review trail)")
        if not reviewer or not reviewer.startswith("role."):
            raise EditError("reviewer must be a role (e.g. role.qms.iso_advisor)")

        current = self.guardrail(gr_id)
        new = copy.deepcopy(current)

        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise EditError(f"these fields are not owner-editable: {sorted(unknown)}")
        for k, v in changes.items():
            new[k] = v

        # governance-time lint: the escalate_if must parse under the SAME evaluator
        # the Enforcement Point runs, or a bad condition would reach agents.
        if new.get("escalate_if"):
            try:
                cc._safe_eval(new["escalate_if"], {})
            except Exception as e:  # noqa: BLE001
                raise EditError(f"escalate_if is not a valid condition: {e}")

        new["version"] = current["version"] + 1
        new["status"] = new.get("status", "active")
        new["review"] = {"reviewed_by": reviewer, "reviewed_at": _now(),
                         "note": reason.strip()}

        errs = sorted(self._gr_validator.iter_errors(new), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(f"{list(e.path) or '(root)'}: {e.message}" for e in errs[:4]))

        cc.append_edit_event(
            "GuardrailPolicy", gr_id, "update",
            from_version=current["version"], to_version=new["version"],
            actor={"kind": "human", "id": actor}, payload=new, reason=reason.strip(),
        )
        return new

    # --- Task write path (edit process structure on the canvas) ------------
    def _validate_task(self, task: dict, g: cc.Graph) -> None:
        errs = sorted(self._task_validator.iter_errors(task), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(f"{list(e.path) or '(root)'}: {e.message}" for e in errs[:3]))
        if g.get("Process", task["process_ref"]) is None:
            raise EditError(f"unknown process {task['process_ref']}")
        for w in task["performed_by"]:  # referential integrity — no dangling performers
            if w.startswith("role.") and g.get("HumanRole", w) is None:
                raise EditError(f"unknown role {w}")
            if w.startswith("agent.") and g.get("AgentBinding", w) is None:
                raise EditError(f"unknown agent binding {w}")
        if task.get("guardrail_ref") and g.get("GuardrailPolicy", task["guardrail_ref"]) is None:
            raise EditError(f"unknown guardrail {task['guardrail_ref']}")

    def _require(self, reason: str, actor: str) -> None:
        if not reason or not reason.strip():
            raise EditError("a change reason is required (ISO 9001 §7.5 review trail)")
        if not actor or not actor.startswith("role."):
            raise EditError("actor must be a role")

    def _active_tasks(self, g: cc.Graph, process_ref: str) -> list[dict]:
        return sorted((t for t in g.all("Task")
                       if t["process_ref"] == process_ref and t["status"] == "active"),
                      key=lambda t: t["seq"])

    def edit_task(self, task_id: str, changes: dict, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        cur = g.get("Task", task_id)
        if cur is None or cur["status"] != "active":
            raise EditError(f"unknown or retired task {task_id}")
        unknown = set(changes) - set(EDITABLE_TASK_FIELDS)
        if unknown:
            raise EditError(f"these fields are not editable: {sorted(unknown)}")
        if changes.get("subprocess_ref"):
            sp = changes["subprocess_ref"]
            if sp == cur["process_ref"]:
                raise EditError("a step can't drill down into its own process")
            tgt = g.get("Process", sp)
            if tgt is None or tgt["status"] != "active":
                raise EditError(f"unknown sub-process {sp}")
        new = copy.deepcopy(cur)
        for k, v in changes.items():
            new[k] = v
        new["version"] = cur["version"] + 1
        self._validate_task(new, g)
        cc.append_edit_event("Task", task_id, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def add_task(self, process_ref: str, name: str, actor: str, reason: str,
                 performed_by: list[str] | None = None, after: str | None = None) -> dict:
        """Insert a step. after=None appends; after='__start__' prepends; after=<task id>
        inserts right after that step. Steps below the insertion point shift down —
        each a versioned update, so the reorder is fully on the §7.5 trail."""
        self._require(reason, actor)
        if not name or not name.strip():
            raise EditError("a step name is required")
        g = self.graph()
        proc = g.get("Process", process_ref)
        if proc is None:
            raise EditError(f"unknown process {process_ref}")
        sibs = self._active_tasks(g, process_ref)

        if after is None:                                   # append at the end
            seq = max((t["seq"] for t in sibs), default=0) + 1
        elif after == "__start__":                          # prepend
            seq = 1
        else:                                               # insert after a given step
            aft = g.get("Task", after)
            if aft is None or aft["process_ref"] != process_ref or aft["status"] != "active":
                raise EditError(f"cannot insert after unknown step {after}")
            seq = aft["seq"] + 1

        for t in sibs:                                      # shift the tail down, versioned
            if t["seq"] >= seq:
                nv = copy.deepcopy(t)
                nv["seq"] = t["seq"] + 1
                nv["version"] = t["version"] + 1
                cc.append_edit_event("Task", t["id"], "update", t["version"], nv["version"],
                                     {"kind": "human", "id": actor}, nv, "shift for insert")

        # number over ALL tasks (incl. retired) so ids are never reused
        num = max((int(t["id"].split(".t")[-1])
                   for t in g.all("Task") if t["process_ref"] == process_ref), default=0) + 1
        new = {
            "id": f"{process_ref}.t{num}", "process_ref": process_ref, "seq": seq,
            "name": name.strip(), "inputs": [], "outputs": [], "data_scope": [],
            "kpi_refs": [], "performed_by": performed_by or [proc["owner_role"]],
            "guardrail_ref": None, "version": 1, "status": "active",
        }
        self._validate_task(new, g)
        cc.append_edit_event("Task", new["id"], "create", None, 1,
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def bind_agent(self, task_id: str, actor: str, reason: str,
                   model: str = "claude-opus-4-8", mcp_tool: str | None = None) -> dict:
        """Make a step agent-run: create an AgentBinding for it and add the agent to
        the step's performers. The binding is created first so the task-update
        validates. The step then shows as agent-bound (AI badge, guardrail
        escalation branch) and counts toward §12 coverage."""
        self._require(reason, actor)
        g = self.graph()
        t = g.get("Task", task_id)
        if t is None or t["status"] != "active":
            raise EditError(f"unknown or retired step {task_id}")
        if any(w.startswith("agent.") for w in t["performed_by"]):
            raise EditError("this step already has an agent binding")

        base = "agent." + task_id.lower()
        existing = {b["id"] for b in g.all("AgentBinding")}
        aid, n = base, 2
        while aid in existing:
            aid = f"{base}_{n}"; n += 1
        binding = {
            "id": aid, "task_ref": task_id,
            "mcp_tool": mcp_tool or ("continuum." + task_id.split(".")[0].lower()),
            "model": model, "guardrail_ref": None, "version": 1, "status": "active",
        }
        errs = sorted(self._binding_validator.iter_errors(binding), key=lambda e: list(e.path))
        if errs:
            raise EditError("agent binding invalid: " + "; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("AgentBinding", aid, "create", None, 1,
                             {"kind": "human", "id": actor}, binding, reason.strip())
        # now the binding exists, so this task update validates
        self.edit_task(task_id, {"performed_by": t["performed_by"] + [aid]}, actor, reason)
        return {"binding": aid, "task": task_id}

    def unbind_agent(self, task_id: str, actor: str, reason: str) -> dict:
        """Make a step human-only again: drop the agent from its performers and
        deprecate the binding (retained, never hard-deleted)."""
        self._require(reason, actor)
        g = self.graph()
        t = g.get("Task", task_id)
        if t is None:
            raise EditError(f"unknown step {task_id}")
        agents = [w for w in t["performed_by"] if w.startswith("agent.")]
        if not agents:
            raise EditError("this step has no agent binding")
        self.edit_task(task_id, {"performed_by": [w for w in t["performed_by"] if not w.startswith("agent.")]},
                       actor, reason)
        for aid in agents:
            b = cc.Graph().get("AgentBinding", aid)
            if b and b["status"] == "active":
                nb = copy.deepcopy(b)
                nb["status"] = "deprecated"
                nb["version"] = b["version"] + 1
                cc.append_edit_event("AgentBinding", aid, "deprecate", b["version"], nb["version"],
                                     {"kind": "human", "id": actor}, nb, reason.strip())
        return {"unbound": agents, "task": task_id}

    def add_process(self, code: str, name: str, owner_role: str, actor: str,
                    reason: str) -> dict:
        """Author a brand-new process. It is stamped with the permissive-but-scoped
        default guardrail template (§11) at creation — unreviewed, so §12 coverage
        counts it as a default until an owner reviews it. Both the guardrail and the
        process are created as versioned, chained events."""
        self._require(reason, actor)
        if not name or not name.strip():
            raise EditError("a process name is required")
        if not re.match(r"^[A-Z]{2}\.[0-9]+(\.[0-9]+)*$", code or ""):
            raise EditError("code must look like an APQC path, e.g. QA.5.1.1")
        g = self.graph()
        if g.get("Process", code) is not None:
            raise EditError(f"process {code} already exists")
        if g.get("HumanRole", owner_role) is None:
            raise EditError(f"unknown owner role {owner_role}")

        # default guardrail from the signed-off template — but as a fresh, UNREVIEWED
        # instance (no review block) so coverage tracks that it still needs review.
        d = self._default_gr
        gr_id = "gr." + code
        gr = {"id": gr_id, "attaches_to": {"kind": "process", "ref": code},
              "allowed_actions": d["allowed_actions"], "forbidden_actions": d["forbidden_actions"],
              "escalate_if": d["escalate_if"], "data_scope": [], "rate_limit": d["rate_limit"],
              "escalation_path": owner_role, "audit_requirement": d["audit_requirement"],
              "version": 1, "status": "active"}
        errs = sorted(self._gr_validator.iter_errors(gr), key=lambda e: list(e.path))
        if errs:
            raise EditError("default guardrail invalid: " + "; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("GuardrailPolicy", gr_id, "create", None, 1,
                             {"kind": "human", "id": actor}, gr, reason.strip())

        proc = {"id": code, "apqc_code": code, "name": name.strip(), "owner_role": owner_role,
                "inputs": [], "outputs": [], "kpi_refs": [], "risk_refs": [],
                "guardrail_ref": gr_id, "maturity_score": None, "version": 1, "status": "active"}
        perrs = sorted(self._process_validator.iter_errors(proc), key=lambda e: list(e.path))
        if perrs:
            raise EditError("; ".join(f"{list(e.path) or '(root)'}: {e.message}" for e in perrs[:3]))
        cc.append_edit_event("Process", code, "create", None, 1,
                             {"kind": "human", "id": actor}, proc, reason.strip())
        return proc

    # --- roles (master data) ------------------------------------------------
    def role_refs(self, g: cc.Graph, role_id: str) -> dict:
        """Every active place a role is referenced, so a role is never edited or
        removed blind. Returns {as_owner, as_performer, as_escalation, as_objective_owner}."""
        owner = [p["id"] for p in g.all("Process")
                 if p["status"] == "active" and p.get("owner_role") == role_id]
        performer = [t["id"] for t in g.all("Task")
                     if t["status"] == "active" and role_id in t.get("performed_by", [])]
        escalation = [gr["id"] for gr in g.all("GuardrailPolicy")
                      if gr.get("status") == "active" and gr.get("escalation_path") == role_id]
        objective = [o["id"] for o in g.all("StrategicObjective")
                     if o.get("owner_role") == role_id]
        return {"as_owner": owner, "as_performer": performer,
                "as_escalation": escalation, "as_objective_owner": objective}

    def add_role(self, role_id: str, name: str, actor: str, reason: str,
                 raci: dict | None = None, skills: list[str] | None = None) -> dict:
        """Author a new HumanRole — a role, never a named person (§02). Validated
        against the locked schema and recorded as a versioned, chained event."""
        self._require(reason, actor)
        if not re.match(r"^role\.[a-z0-9_.]+$", role_id or ""):
            raise EditError("a role id must look like role.dept.name (lowercase, dots/underscores)")
        if not name or not name.strip():
            raise EditError("a role name is required")
        g = self.graph()
        if g.get("HumanRole", role_id) is not None:
            raise EditError(f"role {role_id} already exists")
        role = {"id": role_id, "name": name.strip(), "version": 1, "status": "active"}
        if raci:
            role["raci"] = {k: bool(v) for k, v in raci.items()
                            if k in ("responsible", "accountable", "consulted", "informed")}
        if skills:
            role["skills"] = [str(s).strip() for s in skills if str(s).strip()]
        errs = sorted(self._role_validator.iter_errors(role), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("HumanRole", role_id, "create", None, 1,
                             {"kind": "human", "id": actor}, role, reason.strip())
        return role

    def edit_role(self, role_id: str, changes: dict, actor: str, reason: str) -> dict:
        """Rename a role or update its standing RACI / skills. The id is immutable
        (it is referenced across the graph); a new version, never an overwrite."""
        self._require(reason, actor)
        g = self.graph()
        cur = g.get("HumanRole", role_id)
        if cur is None or cur["status"] != "active":
            raise EditError(f"unknown or retired role {role_id}")
        unknown = set(changes) - set(EDITABLE_ROLE_FIELDS)
        if unknown:
            raise EditError(f"these fields are not editable: {sorted(unknown)} (the role id is immutable)")
        new = copy.deepcopy(cur)
        for k, v in changes.items():
            if k == "raci":
                new["raci"] = {kk: bool(vv) for kk, vv in (v or {}).items()
                               if kk in ("responsible", "accountable", "consulted", "informed")}
            elif k == "skills":
                new["skills"] = [str(s).strip() for s in (v or []) if str(s).strip()]
            elif k == "name":
                if not str(v).strip():
                    raise EditError("a role name is required")
                new["name"] = str(v).strip()
        new["version"] = cur["version"] + 1
        errs = sorted(self._role_validator.iter_errors(new), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("HumanRole", role_id, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def remove_role(self, role_id: str, actor: str, reason: str) -> dict:
        """Retire a role — refused while anything still references it, so no owner,
        performer, or escalation path is left pointing at nothing."""
        self._require(reason, actor)
        g = self.graph()
        cur = g.get("HumanRole", role_id)
        if cur is None or cur["status"] != "active":
            raise EditError(f"unknown or already-retired role {role_id}")
        refs = self.role_refs(g, role_id)
        used = refs["as_owner"] + refs["as_performer"] + refs["as_escalation"] + refs["as_objective_owner"]
        if used:
            raise EditError(f"role {role_id} is still in use by {len(used)} item(s) "
                            f"(e.g. {used[0]}); reassign them before retiring it")
        new = copy.deepcopy(cur)
        new["status"] = "deprecated"
        new["version"] = cur["version"] + 1
        cc.append_edit_event("HumanRole", role_id, "deprecate", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def move_task(self, task_id: str, direction: str, actor: str,
                  reason: str = "reorder step") -> dict:
        self._require(reason, actor)
        g = self.graph()
        t = g.get("Task", task_id)
        if t is None or t["status"] != "active":
            raise EditError(f"unknown or retired task {task_id}")
        sibs = self._active_tasks(g, t["process_ref"])
        idx = next(i for i, x in enumerate(sibs) if x["id"] == task_id)
        j = idx - 1 if direction == "up" else idx + 1
        if j < 0 or j >= len(sibs):
            raise EditError(f"cannot move {direction}: already at the {'top' if direction == 'up' else 'bottom'}")
        other = sibs[j]
        for one, newseq in ((t, other["seq"]), (other, t["seq"])):  # swap seqs, both versioned
            nv = copy.deepcopy(one)
            nv["seq"] = newseq
            nv["version"] = one["version"] + 1
            cc.append_edit_event("Task", one["id"], "update", one["version"], nv["version"],
                                 {"kind": "human", "id": actor}, nv, reason.strip())
        return {"moved": task_id, "direction": direction}

    def remove_task(self, task_id: str, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        t = g.get("Task", task_id)
        if t is None or t["status"] != "active":
            raise EditError(f"unknown or already-retired task {task_id}")
        new = copy.deepcopy(t)
        new["status"] = "deprecated"          # never hard-deleted (ISO 9001 §7.5)
        new["version"] = t["version"] + 1
        cc.append_edit_event("Task", task_id, "deprecate", t["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    # --- Phase B: gateways + sequence flows (explicit process-flow graph) ---
    def _active(self, g: cc.Graph, etype: str, process_ref: str) -> list[dict]:
        return [e for e in g.all(etype)
                if e.get("process_ref") == process_ref and e.get("status") == "active"]

    def _node_ok(self, g: cc.Graph, process_ref: str, node: str) -> bool:
        if node in ("__start__", "__end__"):
            return True
        for et in ("Task", "Gateway", "Event"):
            e = g.get(et, node)
            if e and e.get("process_ref") == process_ref and e.get("status") == "active":
                return True
        return False

    def add_gateway(self, process_ref: str, gtype: str, actor: str, reason: str,
                    name: str = "") -> dict:
        """Create a decision (exclusive/XOR) or fork-join (parallel/AND) node."""
        self._require(reason, actor)
        if gtype not in ("exclusive", "parallel"):
            raise EditError("gateway type must be 'exclusive' or 'parallel'")
        g = self.graph()
        if g.get("Process", process_ref) is None:
            raise EditError(f"unknown process {process_ref}")
        num = max((int(x["id"].split(".g")[-1]) for x in g.all("Gateway")
                   if x["process_ref"] == process_ref), default=0) + 1
        gw = {"id": f"{process_ref}.g{num}", "process_ref": process_ref, "type": gtype,
              "name": name.strip(), "version": 1, "status": "active"}
        errs = sorted(self._gateway_validator.iter_errors(gw), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("Gateway", gw["id"], "create", None, 1,
                             {"kind": "human", "id": actor}, gw, reason.strip())
        return gw

    def remove_gateway(self, gateway_id: str, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        gw = g.get("Gateway", gateway_id)
        if gw is None or gw["status"] != "active":
            raise EditError(f"unknown or already-retired gateway {gateway_id}")
        # cascade: retire the flows touching it, so no edge dangles (all versioned)
        for f in self._active(g, "SequenceFlow", gw["process_ref"]):
            if gateway_id in (f["from_node"], f["to_node"]):
                self._retire_flow(f, actor, "gateway removed")
        new = copy.deepcopy(gw)
        new["status"] = "deprecated"
        new["version"] = gw["version"] + 1
        cc.append_edit_event("Gateway", gateway_id, "deprecate", gw["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def _retire_flow(self, f: dict, actor: str, reason: str) -> dict:
        new = copy.deepcopy(f)
        new["status"] = "deprecated"
        new["version"] = f["version"] + 1
        cc.append_edit_event("SequenceFlow", f["id"], "deprecate", f["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason)
        return new

    def add_event(self, process_ref: str, kind: str, trigger: str, actor: str, reason: str,
                  name: str = "", timer: str | None = None, message_ref: str | None = None) -> dict:
        """Create a timer / message (or plain start / end) event node. Structural,
        like a gateway — it carries no guardrail; it just routes the flow."""
        self._require(reason, actor)
        if kind not in ("start", "intermediate", "end"):
            raise EditError("event kind must be 'start', 'intermediate', or 'end'")
        if trigger not in ("none", "timer", "message"):
            raise EditError("event trigger must be 'none', 'timer', or 'message'")
        g = self.graph()
        if g.get("Process", process_ref) is None:
            raise EditError(f"unknown process {process_ref}")
        num = max((int(x["id"].split(".e")[-1]) for x in g.all("Event")
                   if x["process_ref"] == process_ref), default=0) + 1
        ev = {"id": f"{process_ref}.e{num}", "process_ref": process_ref, "kind": kind,
              "trigger": trigger, "name": name.strip(),
              "timer": (timer.strip() or None) if timer else None,
              "message_ref": (message_ref.strip() or None) if message_ref else None,
              "version": 1, "status": "active"}
        errs = sorted(self._event_validator.iter_errors(ev), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("Event", ev["id"], "create", None, 1,
                             {"kind": "human", "id": actor}, ev, reason.strip())
        return ev

    def remove_event(self, event_id: str, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        ev = g.get("Event", event_id)
        if ev is None or ev["status"] != "active":
            raise EditError(f"unknown or already-retired event {event_id}")
        # cascade: retire flows touching it, so no edge dangles (all versioned)
        for f in self._active(g, "SequenceFlow", ev["process_ref"]):
            if event_id in (f["from_node"], f["to_node"]):
                self._retire_flow(f, actor, "event removed")
        new = copy.deepcopy(ev)
        new["status"] = "deprecated"
        new["version"] = ev["version"] + 1
        cc.append_edit_event("Event", event_id, "deprecate", ev["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def add_flow(self, process_ref: str, from_node: str, to_node: str, actor: str,
                 reason: str, condition: str | None = None) -> dict:
        """Draw a directed edge between two nodes (task / gateway / start / end)."""
        self._require(reason, actor)
        g = self.graph()
        if g.get("Process", process_ref) is None:
            raise EditError(f"unknown process {process_ref}")
        if from_node == to_node:
            raise EditError("a flow cannot loop a node to itself")
        if from_node == "__end__" or to_node == "__start__":
            raise EditError("flows go start -> ... -> end, not the other way")
        if not self._node_ok(g, process_ref, from_node):
            raise EditError(f"unknown source node {from_node}")
        if not self._node_ok(g, process_ref, to_node):
            raise EditError(f"unknown target node {to_node}")
        for f in self._active(g, "SequenceFlow", process_ref):
            if f["from_node"] == from_node and f["to_node"] == to_node:
                raise EditError("that flow already exists")
        num = max((int(x["id"].split(".f")[-1]) for x in g.all("SequenceFlow")
                   if x["process_ref"] == process_ref), default=0) + 1
        flow = {"id": f"{process_ref}.f{num}", "process_ref": process_ref,
                "from_node": from_node, "to_node": to_node,
                "condition": (condition.strip() or None) if condition else None,
                "version": 1, "status": "active"}
        errs = sorted(self._flow_validator.iter_errors(flow), key=lambda e: list(e.path))
        if errs:
            raise EditError("; ".join(e.message for e in errs[:2]))
        cc.append_edit_event("SequenceFlow", flow["id"], "create", None, 1,
                             {"kind": "human", "id": actor}, flow, reason.strip())
        return flow

    def remove_flow(self, flow_id: str, actor: str, reason: str) -> dict:
        self._require(reason, actor)
        g = self.graph()
        f = g.get("SequenceFlow", flow_id)
        if f is None or f["status"] != "active":
            raise EditError(f"unknown or already-retired flow {flow_id}")
        return self._retire_flow(f, actor, reason.strip())

    def enable_branching(self, process_ref: str, actor: str, reason: str) -> list[dict]:
        """Seed explicit flows from the current linear task sequence, so a process
        that has only an implicit order gains an editable graph without losing it."""
        self._require(reason, actor)
        g = self.graph()
        if g.get("Process", process_ref) is None:
            raise EditError(f"unknown process {process_ref}")
        if self._active(g, "SequenceFlow", process_ref):
            raise EditError("this process already has an explicit flow")
        tasks = sorted(self._active_tasks(g, process_ref), key=lambda t: t["seq"])
        if not tasks:
            raise EditError("add at least one step before enabling branching")
        chain = ["__start__"] + [t["id"] for t in tasks] + ["__end__"]
        out = []
        for a, b in zip(chain, chain[1:]):
            out.append(self.add_flow(process_ref, a, b, actor, reason))
        return out

    # --- helpers -----------------------------------------------------------
    @staticmethod
    def _read_log(path: str) -> list[dict]:
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


if __name__ == "__main__":
    s = GovernanceStore()
    print(json.dumps(s.process_list(), indent=2)[:1200])
