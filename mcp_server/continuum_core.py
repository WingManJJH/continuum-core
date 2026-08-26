"""
Continuum Core — framework-independent prototype engine.

Loads the hand-built object graph (../data/seed.json), resolves guardrail
inheritance, and emits the compact, token-cheap packages defined in Core Model
§03 and budgeted in §08. The MCP server (server.py) is a thin wrapper over the
three public tool functions here; the token harness (token_budget.py) measures
their output. Nothing here imports the MCP SDK, so the logic is testable on its
own.

Design rule (§08): the wire format is flat YAML-ish text — IDs and enums, no
prose, no braces/quotes tax — because the budgets are calibrated to that render,
not to pretty-printed JSON.
"""
from __future__ import annotations

import ast
import json
import os
from datetime import datetime, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.normpath(os.path.join(HERE, "..", "data", "seed.json"))
EVENTS_LOG = os.path.join(os.path.dirname(DATA), "events.log.jsonl")   # agent actions (§04/§06)
EDITS_LOG = os.path.join(os.path.dirname(DATA), "edits.log.jsonl")     # change control (Phase 2 governance edits, ISO 9001 §7.5)

REASON_CODES = {
    "allowed",
    "action_forbidden",     # action is on the explicit deny-list
    "action_not_allowed",   # action is not on the allow-list (implicit deny)
    "escalate_if_met",      # escalate_if condition evaluated true
    "out_of_scope",         # action would touch fields outside data_scope
    "rate_limited",         # over rate_limit (not enforced in this stateless prototype)
}


class Graph:
    """In-memory fold of the seed graph, indexed by id per entity type."""

    def __init__(self, path: str = DATA, apply_edits: bool = True):
        with open(path) as f:
            raw = json.load(f)
        self.model_sig: str = raw.get("model_sig", "dev")
        self._by_type: dict[str, dict[str, dict]] = {}
        for etype in (
            "StrategicObjective", "KPI", "Process", "Task",
            "HumanRole", "AgentBinding", "GuardrailPolicy", "RiskControl",
        ):
            self._by_type[etype] = {e["id"]: e for e in raw.get(etype, [])}
        # Fold the change-control log on top of the seed baseline so the state an
        # agent reads over MCP is the SAME state a governance edit produced — one
        # source of truth, edits are data not deploys (Core Model §01/§04, Phase 2).
        if apply_edits:
            self.apply_edit_log()

    def apply_edit_log(self, log_path: str = EDITS_LOG) -> None:
        if not os.path.exists(log_path):
            return
        with open(log_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = json.loads(line)
                et, eid, op = ev["entity_type"], ev["entity_id"], ev["op"]
                if op in ("create", "update", "restore"):
                    self._by_type[et][eid] = ev["payload"]
                elif op == "deprecate" and eid in self._by_type[et]:
                    self._by_type[et][eid]["status"] = "deprecated"

    def get(self, etype: str, _id: str) -> dict | None:
        return self._by_type[etype].get(_id)

    def all(self, etype: str) -> list[dict]:
        return list(self._by_type[etype].values())

    # --- guardrail inheritance (SCHEMA.md "Guardrail inheritance") ---------
    def effective_guardrail(self, task_id: str) -> tuple[dict | None, str | None]:
        """Return (guardrail_policy, version_pinned_ref) for a task.
        Task override wins; otherwise inherit the owning process's guardrail."""
        task = self.get("Task", task_id)
        if task is None:
            return None, None
        gr_id = task.get("guardrail_ref")
        if not gr_id:
            proc = self.get("Process", task["process_ref"])
            gr_id = proc.get("guardrail_ref") if proc else None
        if not gr_id:
            return None, None
        gr = self.get("GuardrailPolicy", gr_id)
        if gr is None:
            return None, None
        pinned = f"{gr_id}.v{gr['version']}"
        return gr, pinned


# --------------------------------------------------------------------------
# Compact emitters — the flat §03 render. Kept tiny on purpose.
# --------------------------------------------------------------------------
def _arr(items: list[str]) -> str:
    return "[" + ", ".join(items) + "]"


def render_task_context(g: Graph, task_id: str) -> str:
    """get_task_context payload — Core Model §03, budget < 150 tokens (§08)."""
    task = g.get("Task", task_id)
    if task is None:
        return f"error: unknown_task {task_id}"
    gr, pinned = g.effective_guardrail(task_id)
    short_task = task_id.split(".t")[-1]
    # Single-space keys, not column-aligned: the alignment whitespace is a
    # decorative property an agent never needs, and stripping it is the §08
    # discipline applied to the payload itself (see token_budget.py findings).
    lines = [
        f"proc: {task['process_ref']}",
        f"task: t{short_task}",
        f'name: "{task["name"]}"',
        f"owner: {task['performed_by'][0]}",
        f"in: {_arr(task['inputs'])}",
        f"out: {_arr(task['outputs'])}",
        f"kpi: {_arr(task.get('kpi_refs', []))}",
    ]
    if gr:
        lines += [
            "guardrail:",
            f"  ref: {pinned}",
            f"  allow: {_arr(gr['allowed_actions'])}",
            f"  deny: {_arr(gr['forbidden_actions'])}",
            f"  escalate_if: {gr.get('escalate_if') or 'none'}",
            f"  scope: {_arr(gr['data_scope'])}",
        ]
    lines.append(f"model_sig: {g.model_sig}")
    return "\n".join(lines)


def _safe_eval(expr: str, facts: dict[str, Any]) -> bool:
    """Evaluate an escalate_if expression over `facts` with a whitelisted AST.
    Supports comparisons, and/or/not, parentheses, names, numbers, booleans.
    Any unknown name resolves to None -> comparison is False, never an error."""
    if not expr:
        return False
    tree = ast.parse(expr, mode="eval")

    def ev(node):
        if isinstance(node, ast.Expression):
            return ev(node.body)
        if isinstance(node, ast.BoolOp):
            vals = [ev(v) for v in node.values]
            return all(vals) if isinstance(node.op, ast.And) else any(vals)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            return not ev(node.operand)
        if isinstance(node, ast.Compare):
            left = ev(node.left)
            for op, comp in zip(node.ops, node.comparators):
                right = ev(comp)
                if left is None or right is None:
                    return False
                if not _cmp(op, left, right):
                    return False
                left = right
            return True
        if isinstance(node, ast.Name):
            return facts.get(node.id)
        if isinstance(node, ast.Constant):
            return node.value
        raise ValueError(f"disallowed expression element: {ast.dump(node)}")

    return bool(ev(tree))


def _cmp(op, a, b) -> bool:
    if isinstance(op, ast.Gt):
        return a > b
    if isinstance(op, ast.GtE):
        return a >= b
    if isinstance(op, ast.Lt):
        return a < b
    if isinstance(op, ast.LtE):
        return a <= b
    if isinstance(op, ast.Eq):
        return a == b
    if isinstance(op, ast.NotEq):
        return a != b
    raise ValueError("disallowed comparison operator")


def check_guardrail(g: Graph, task_id: str, action: str,
                    facts: dict | None = None) -> dict:
    """Core decision. Returns a structured verdict; render_guardrail_check()
    turns it into the < 40-token wire payload (§08)."""
    facts = facts or {}
    gr, pinned = g.effective_guardrail(task_id)
    if gr is None:
        return {"decision": "deny", "reason": "action_not_allowed", "gr": None}

    # data-scope check: any touched field outside scope is a hard deny
    touched = facts.get("fields", [])
    if touched and any(fld not in gr["data_scope"] for fld in touched):
        return {"decision": "deny", "reason": "out_of_scope", "gr": pinned}

    if action in gr["forbidden_actions"]:
        return {"decision": "deny", "reason": "action_forbidden", "gr": pinned}
    if action not in gr["allowed_actions"]:
        return {"decision": "deny", "reason": "action_not_allowed", "gr": pinned}
    if _safe_eval(gr.get("escalate_if") or "", facts):
        return {"decision": "escalate", "reason": "escalate_if_met",
                "to": gr["escalation_path"], "gr": pinned}
    return {"decision": "allow", "reason": "allowed", "gr": pinned}


def render_guardrail_check(verdict: dict) -> str:
    """< 40-token wire form: decision + reason code, never a paragraph (§08)."""
    lines = [f"decision: {verdict['decision']}"]
    if verdict["decision"] != "allow":
        lines.append(f"reason: {verdict['reason']}")
    if verdict.get("to"):
        lines.append(f"to: {verdict['to']}")
    if verdict.get("gr"):
        lines.append(f"gr: {verdict['gr']}")
    return "\n".join(lines)


def log_action(g: Graph, task_id: str, action: str, outcome: str,
               guardrail_version: str, actor: str = "agent.kyc_verifier",
               detail: dict | None = None) -> str:
    """Append an immutable action event (§04: agent cites the guardrail version
    it acted under) and return a compact ack. Also the raw feed the signal layer
    aggregates in §06."""
    event = {
        "event_id": "evt_" + _ulidish(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "entity_type": "Task",
        "entity_id": task_id,
        "op": "update",
        "to_version": g.get("Task", task_id)["version"] if g.get("Task", task_id) else 1,
        "actor": {"kind": "agent", "id": actor},
        "reason": f"agent action: {action} -> {outcome}",
        "payload": {
            "action": action,
            "outcome": outcome,
            "guardrail_version": guardrail_version,
            "detail": detail or {},
        },
    }
    with open(EVENTS_LOG, "a") as f:
        f.write(json.dumps(event) + "\n")
    return f"logged: {event['event_id']}\ntask: {task_id}\ncited_gr: {guardrail_version}"


def append_edit_event(entity_type: str, entity_id: str, op: str,
                      from_version: int | None, to_version: int,
                      actor: dict, payload: dict, reason: str,
                      log_path: str = EDITS_LOG) -> dict:
    """Append an immutable change-control event to the edit log (ISO 9001 §7.5).
    This is the write path Phase-2 governance edits go through — a new version,
    never an overwrite. Returns the event. Stdlib-only so the core stays light."""
    event = {
        "event_id": "evt_" + _ulidish(),
        "ts": datetime.now(timezone.utc).isoformat(),
        "entity_type": entity_type,
        "entity_id": entity_id,
        "op": op,
        "from_version": from_version,
        "to_version": to_version,
        "actor": actor,
        "reason": reason,
        "payload": payload,
    }
    with open(log_path, "a") as f:
        f.write(json.dumps(event) + "\n")
    return event


def render_process_summary(g: Graph, process_id: str) -> str:
    """Task-list plan payload — budget < 400 tokens (§08)."""
    proc = g.get("Process", process_id)
    if proc is None:
        return f"error: unknown_process {process_id}"
    _, pinned = _proc_guardrail(g, proc)
    lines = [
        f"proc: {proc['apqc_code']}",
        f'name: "{proc["name"]}"',
        f"owner: {proc['owner_role']}",
        f"guardrail: {pinned}",
        f"kpi: {_arr(proc.get('kpi_refs', []))}",
        "tasks:",
    ]
    tasks = sorted((t for t in g.all("Task") if t["process_ref"] == process_id),
                   key=lambda t: t["seq"])
    for t in tasks:
        short = t["id"].split(".t")[-1]
        lines.append(f'  t{short} seq{t["seq"]} "{t["name"]}" by:{_arr(t["performed_by"])}')
    return "\n".join(lines)


def render_strategy_rollup(g: Graph, objective_id: str) -> str:
    """Objective -> KPI status payload — budget < 250 tokens (§08)."""
    obj = g.get("StrategicObjective", objective_id)
    if obj is None:
        return f"error: unknown_objective {objective_id}"
    lines = [
        f"obj:     {obj['id']}",
        f"owner:   {obj['owner_role']}",
        f"horizon: {obj['horizon']}",
        "kpi:",
    ]
    for kref in obj.get("kpi_refs", []):
        k = g.get("KPI", kref)
        if not k:
            lines.append(f"  {kref}: MISSING  # data-quality defect")
            continue
        status = _kpi_status(k)
        lv = k.get("live_value")
        lines.append(f"  {kref}: {lv}/{k['target']} {k['unit']} {status}")
    return "\n".join(lines)


# --- helpers ---------------------------------------------------------------
def _proc_guardrail(g: Graph, proc: dict) -> tuple[dict | None, str | None]:
    gr_id = proc.get("guardrail_ref")
    if not gr_id:
        return None, None
    gr = g.get("GuardrailPolicy", gr_id)
    if not gr:
        return None, None
    return gr, f"{gr_id}.v{gr['version']}"


def _kpi_status(k: dict) -> str:
    lv = k.get("live_value")
    if lv is None:
        return "no_data"
    if k["direction"] == "lower_is_better":
        return "on_target" if lv <= k["target"] else "off_target"
    return "on_target" if lv >= k["target"] else "off_target"


_COUNTER = [0]


def _ulidish() -> str:
    """Monotonic-ish id without Math.random; fine for a single-process prototype."""
    _COUNTER[0] += 1
    base = int(datetime.now(timezone.utc).timestamp() * 1000)
    raw = f"{base:011X}{_COUNTER[0]:015X}"
    return raw[:26]


# public tool surface used by server.py -------------------------------------
def get_task_context(task_id: str, g: Graph | None = None) -> str:
    return render_task_context(g or Graph(), task_id)


def guardrail_check(task_id: str, action: str, facts: dict | None = None,
                    g: Graph | None = None) -> str:
    g = g or Graph()
    return render_guardrail_check(check_guardrail(g, task_id, action, facts))


if __name__ == "__main__":
    g = Graph()
    print("--- get_task_context('CO.3.2.7.t3') ---")
    print(render_task_context(g, "CO.3.2.7.t3"))
    print("\n--- check_guardrail(t3, verify_document, risk_score=0.9) ---")
    print(render_guardrail_check(check_guardrail(g, "CO.3.2.7.t3", "verify_document", {"risk_score": 0.9})))
    print("\n--- process_summary('CO.3.2.7') ---")
    print(render_process_summary(g, "CO.3.2.7"))
    print("\n--- strategy_rollup('obj.reduce_onboarding_friction') ---")
    print(render_strategy_rollup(g, "obj.reduce_onboarding_friction"))
