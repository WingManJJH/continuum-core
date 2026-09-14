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
    "kpi_refs", "guardrail_ref",
]


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
        new = copy.deepcopy(cur)
        for k, v in changes.items():
            new[k] = v
        new["version"] = cur["version"] + 1
        self._validate_task(new, g)
        cc.append_edit_event("Task", task_id, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def add_task(self, process_ref: str, name: str, actor: str, reason: str,
                 performed_by: list[str] | None = None) -> dict:
        self._require(reason, actor)
        if not name or not name.strip():
            raise EditError("a step name is required")
        g = self.graph()
        proc = g.get("Process", process_ref)
        if proc is None:
            raise EditError(f"unknown process {process_ref}")
        sibs = self._active_tasks(g, process_ref)
        num = max((int(t["id"].split(".t")[-1]) for t in sibs), default=0) + 1
        seq = max((t["seq"] for t in sibs), default=0) + 1
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
