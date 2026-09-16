"""
Approval policy — Phase 3 (Core Model §07/§09, ISO 9001 §5.3/§8.5.6).

Which *kinds* of change must go through the review gate, which may, and which
never do — set per entity type, not per click. Three modes:

  - required : a direct edit is refused; the change must be submitted for review.
  - optional : the editor offers a "Submit for approval" choice (default off).
  - off      : no gate; the change commits directly.

The policy is itself governed: each change is appended to a hash-chained log
(data/approval-policy.log.jsonl) with who / when / why, and the current policy is
folded from that log over the built-in defaults — the same event-sourced pattern
the graph and the approval queue use. Changing the policy is an admin act; the
setter requires a role actor and a reason.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

MODES = ("off", "optional", "required")

# Entity types the policy covers, in display order. The last two are coarse
# buckets for high-frequency structural / matrix edits.
GATED_ENTITIES = [
    ("GuardrailPolicy", "Guardrails"),
    ("Task", "Process steps"),
    ("Process", "Processes"),
    ("ProcessGroup", "Process groups (architecture)"),
    ("HumanRole", "Roles"),
    ("Enterprise", "Enterprise (mission / vision / values)"),
    ("StrategicObjective", "Objectives"),
    ("KPI", "KPIs"),
    ("Initiative", "Initiatives"),
    ("Correlation", "X-matrix links"),
    ("Structural", "Gateways / events / flows"),
]
ENTITY_LABEL = dict(GATED_ENTITIES)

# Which store op touches which policy entity (used by the API/UI and the gate).
OP_ENTITY = {
    "edit_guardrail": "GuardrailPolicy",
    "edit_task": "Task", "add_task": "Task", "move_task": "Task",
    "remove_task": "Task", "bind_agent": "Task", "unbind_agent": "Task",
    "add_process": "Process", "edit_process": "Process",
    "add_group": "ProcessGroup", "edit_group": "ProcessGroup", "remove_group": "ProcessGroup",
    "add_role": "HumanRole", "edit_role": "HumanRole", "remove_role": "HumanRole",
    "edit_enterprise": "Enterprise",
    "edit_objective": "StrategicObjective",
    "edit_kpi": "KPI",
    "add_initiative": "Initiative", "edit_initiative": "Initiative", "remove_initiative": "Initiative",
    "set_correlation": "Correlation", "clear_correlation": "Correlation",
    "add_gateway": "Structural", "edit_gateway": "Structural", "remove_gateway": "Structural",
    "add_event": "Structural", "edit_event": "Structural", "remove_event": "Structural",
    "add_flow": "Structural", "remove_flow": "Structural", "edit_flow": "Structural",
    "enable_branching": "Structural",
}

# Sensible starting point: the substantive business/governance entities are
# gate-able but not forced; high-frequency drawing/matrix edits are ungated.
DEFAULTS = {
    "GuardrailPolicy": "optional", "Task": "optional", "Process": "optional",
    "ProcessGroup": "optional", "HumanRole": "optional", "Enterprise": "optional",
    "StrategicObjective": "optional", "KPI": "optional", "Initiative": "optional",
    "Correlation": "off", "Structural": "off",
}


class PolicyError(ValueError):
    """A rejected policy change — safe to show in the UI."""


def _policy_log() -> str:
    return os.path.join(os.path.dirname(cc.EDITS_LOG), "approval-policy.log.jsonl")


class ApprovalPolicy:
    def __init__(self, log_path: str | None = None):
        self.log_path = log_path or _policy_log()

    def _events(self) -> list[dict]:
        if not os.path.exists(self.log_path):
            return []
        out = []
        with open(self.log_path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(cc.json.loads(line))
        return out

    def get(self) -> dict:
        """Current mode per entity — defaults, with the log's changes folded on top."""
        pol = dict(DEFAULTS)
        for ev in self._events():
            if ev.get("entity") in pol and ev.get("mode") in MODES:
                pol[ev["entity"]] = ev["mode"]
        return pol

    def mode_for_entity(self, entity: str) -> str:
        return self.get().get(entity, "optional")

    def mode_for_op(self, op: str) -> str:
        return self.mode_for_entity(OP_ENTITY.get(op, ""))

    def entities(self) -> list[dict]:
        pol = self.get()
        return [{"key": k, "label": lbl, "mode": pol.get(k, "optional")}
                for k, lbl in GATED_ENTITIES]

    def requires_gate(self, entity: str) -> bool:
        return self.mode_for_entity(entity) == "required"

    def set(self, entity: str, mode: str, actor: str, reason: str) -> dict:
        if entity not in DEFAULTS:
            raise PolicyError(f"unknown entity type '{entity}'")
        if mode not in MODES:
            raise PolicyError(f"mode must be one of {MODES}")
        if not actor or not actor.startswith("role."):
            raise PolicyError("actor must be a role")
        if not reason or not reason.strip():
            raise PolicyError("a reason is required to change approval policy (§7.5)")
        cc._append_event(self.log_path, {
            "event_id": "pol_" + cc._ulidish(),
            "ts": cc.datetime.now(cc.timezone.utc).isoformat(),
            "kind": "set_policy", "entity": entity, "mode": mode,
            "actor": actor, "reason": reason.strip(),
        })
        return self.get()
