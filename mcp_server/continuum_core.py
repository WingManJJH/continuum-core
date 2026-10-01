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
import hashlib
import json
import os
import sys
import threading
import types
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.normpath(os.path.join(HERE, "..", "data"))         # data/ (default model lives here)
MODELS_DIR = os.path.join(DATA_ROOT, "models")                        # data/models/<slug>/ (alternate models)

import storage  # noqa: E402  (D48: file or Postgres backend behind every read/write below)
from storage import ConflictError  # noqa: E402,F401  (re-exported: a stale edit)

storage.models_dir_hook = lambda: MODELS_DIR  # live: tests and tools may repoint cc.MODELS_DIR

# The active model's paths. `cc.DATA`, `cc.EDITS_LOG`, … read like module globals
# (and tests may still assign them), but resolve per THREAD first: a web request
# runs inside `use_model(slug)`, so two users on two models never see each
# other's model (D49). Outside a request they are the process-wide defaults,
# repointed by set_active_model(). Inside this module, use _p("NAME").
_G = {
    "ACTIVE_MODEL": "default",                                         # which model the stack is folding right now
    "DATA": os.path.join(DATA_ROOT, "seed.json"),
    "EVENTS_LOG": os.path.join(DATA_ROOT, "events.log.jsonl"),         # agent actions (§04/§06)
    "EDITS_LOG": os.path.join(DATA_ROOT, "edits.log.jsonl"),          # change control (ISO 9001 §7.5)
    "HEADS_FILE": os.path.join(DATA_ROOT, "audit_heads.json"),        # per-log chain head + count (truncation/rollback)
}
_TL = threading.local()


def _p(name: str):
    ov = getattr(_TL, "paths", None)
    return ov[name] if ov and name in ov else _G[name]


def _paths_for(slug: str | None) -> dict:
    base = model_base(slug)
    return {"ACTIVE_MODEL": slug or "default", "DATA": os.path.join(base, "seed.json"),
            "EVENTS_LOG": os.path.join(base, "events.log.jsonl"), "EDITS_LOG": os.path.join(base, "edits.log.jsonl"),
            "HEADS_FILE": os.path.join(base, "audit_heads.json")}


@contextmanager
def use_model(slug: str | None, user: dict | None = None):
    """Run the enclosed code against model `slug` on this thread only (a web
    request). `user` (the signed-in person) is recorded on every event written."""
    prev_p, prev_u = getattr(_TL, "paths", None), getattr(_TL, "user", None)
    _TL.paths, _TL.user = _paths_for(slug), user
    try:
        yield _TL.paths["ACTIVE_MODEL"]
    finally:
        _TL.paths, _TL.user = prev_p, prev_u


def current_user() -> dict | None:
    return getattr(_TL, "user", None)


class _CoreModule(types.ModuleType):
    pass


for _name in _G:
    setattr(_CoreModule, _name, property(lambda self, n=_name: _p(n),
                                          lambda self, v, n=_name: _G.__setitem__(n, v)))
sys.modules[__name__].__class__ = _CoreModule

GENESIS_HASH = "0" * 64                                                # prev_hash of the first event in a log


def model_base(slug: str) -> str:
    """The directory holding a model's seed + logs. 'default' is data/ itself."""
    return DATA_ROOT if slug in (None, "", "default") else os.path.join(MODELS_DIR, slug)


def set_active_model(slug: str) -> str:
    """Repoint the process-wide default at model `slug` (a directory of seed +
    logs). Web requests use use_model() instead, so this never leaks across users.
    Returns the resolved slug. 'default' is the original data/ model."""
    _G.update(_paths_for(slug))
    return _G["ACTIVE_MODEL"]


def list_models() -> list[dict]:
    """Registered models: the built-in default plus every data/models/<slug>/ (or
    Postgres workspace) that has a model.json. Each: {slug, name, description, source, active}."""
    active = _p("ACTIVE_MODEL")
    out = [{"slug": "default", "name": "Default model", "source": "seed",
            "description": "The original governed model (data/seed.json).",
            "active": active == "default"}]
    for m in storage.get().list_workspaces():
        out.append({"slug": m["slug"], "name": m.get("name", m["slug"]),
                    "description": m.get("description", ""), "source": m.get("source", ""),
                    "active": active == m["slug"]})
    return out

REASON_CODES = {
    "allowed",
    "action_forbidden",     # action is on the explicit deny-list
    "action_not_allowed",   # action is not on the allow-list (implicit deny)
    "escalate_if_met",      # escalate_if condition evaluated true
    "out_of_scope",         # action would touch fields outside data_scope
    "rate_limited",         # over rate_limit (not enforced in this stateless prototype)
}


# D45 — the five EA / GRC building blocks (schemas in schema/<name>.schema.json).
EA_TYPES = ("Capability", "Application", "Obligation", "Control", "Risk")


class Graph:
    """In-memory fold of the seed graph, indexed by id per entity type."""

    def __init__(self, path: str | None = None, apply_edits: bool = True):
        if path is None:
            path = _p("DATA")    # resolve live (per request / set_active_model)
        raw = storage.get().read_json(path)
        if raw is None:
            raise FileNotFoundError(path)
        self.model_sig: str = raw.get("model_sig", "dev")
        self._by_type: dict[str, dict[str, dict]] = {}
        for etype in (
            "StrategicObjective", "KPI", "Process", "Task",
            "HumanRole", "AgentBinding", "GuardrailPolicy", "RiskControl",
            "Gateway", "SequenceFlow",  # Phase B: explicit process-flow graph
            "Event",  # Phase F: timer / message events (BPMN interchange)
            "ProcessGroup",  # L1–L5 hierarchy (management architecture view)
            "Enterprise", "Initiative", "Correlation",  # Phase 2: strategy layer (OKR / X-matrix)
            "CorrectiveAction",  # Phase 3: CAPA — corrective / preventive action register (ISO 9001 §10.2)
            *EA_TYPES,  # D45: enterprise architecture + GRC building blocks
        ):
            self._by_type[etype] = {e["id"]: e for e in raw.get(etype, [])}
        # Fold the change-control log on top of the seed baseline so the state an
        # agent reads over MCP is the SAME state a governance edit produced — one
        # source of truth, edits are data not deploys (Core Model §01/§04, Phase 2).
        if apply_edits:
            self.apply_edit_log()

    def apply_edit_log(self, log_path: str | None = None) -> None:
        if log_path is None:
            log_path = _p("EDITS_LOG")
        for ev in storage.get().read_lines(log_path):
            et, eid, op = ev["entity_type"], ev["entity_id"], ev["op"]
            # every governance edit carries the full entity in payload
            # (snapshot-per-event), so overlaying it folds create/update/
            # restore/deprecate uniformly — a deprecated entity keeps its
            # bumped version and status:deprecated from the payload.
            if et not in self._by_type:
                continue  # a type this build does not know (newer writer): ignore, never crash
            if op in ("create", "update", "restore", "deprecate") and ev.get("payload"):
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


# --------------------------------------------------------------------------
# Tamper-evident audit chain (ISO 9001 §7.5 hardening).
# Every event links to the previous one by hash, so any edit, deletion,
# reorder, or insertion in an append-only log breaks the chain and is caught by
# verify_log(). A per-log heads file anchors the last hash + count so trailing
# truncation / rollback is caught too. Both writers go through _append_event so
# there is one, and only one, place the chain is maintained.
# --------------------------------------------------------------------------
def _canonical(event: dict) -> str:
    """Deterministic serialization for hashing — sorted keys, no whitespace."""
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_event(event: dict) -> str:
    """SHA-256 over the event with its own `hash` field excluded (but including
    `prev_hash`, so the link is part of what's signed)."""
    return storage.hash_event(event)


def _last_hash(log_path: str) -> str:
    """Hash of the last event already in the log, or GENESIS if the log is new."""
    rows = storage.get().read_lines(log_path)
    return rows[-1].get("hash", GENESIS_HASH) if rows else GENESIS_HASH


def _read_heads() -> dict:
    try:
        return storage.get().read_json(_p("HEADS_FILE"), {}) or {}
    except (json.JSONDecodeError, OSError):
        return {}


def _write_head(log_path: str, head: str, count: int) -> None:
    heads = _read_heads()
    heads[os.path.basename(log_path)] = {"head": head, "count": count}
    storage.get().write_json(_p("HEADS_FILE"), heads)


def _drop_head(log_path: str) -> None:
    heads = _read_heads()
    if heads.pop(os.path.basename(log_path), None) is not None:
        storage.get().write_json(_p("HEADS_FILE"), heads)


def reset_log(log_path: str) -> None:
    """Remove a chained log AND its heads-anchor entry together. Resetting the log
    file alone would leave the anchor pointing at events that no longer exist —
    indistinguishable from tampering — so demos/tests/reset paths must use this,
    not a bare os.remove(), when clearing a log for a fresh run."""
    storage.get().reset_log(log_path, _p("HEADS_FILE"))


def _append_event(log_path: str, event: dict, expect: tuple | None = None) -> dict:
    """Chain `event` onto `log_path`: set prev_hash + hash, append, advance head —
    atomically, serialized across threads and processes. `expect` =
    (entity_type, entity_id, from_version, op) turns on the optimistic-concurrency
    check: a stale from_version raises ConflictError and nothing is written."""
    u = current_user()
    if u and isinstance(event.get("actor"), dict) and "user" not in event["actor"]:
        event["actor"] = {**event["actor"], "user": u.get("email") or u.get("id")}
    return storage.get().append_chained(log_path, event, _p("HEADS_FILE"), expect=expect, seed_path=_p("DATA"))


def verify_log(log_path: str, heads_path: str | None = None) -> dict:
    """Re-walk a log and confirm the chain is intact. Returns a structured result
    with the first break (if any) and the heads-anchor check (heads_path defaults
    to the active model's)."""
    name = os.path.basename(log_path)
    be = storage.get()
    _heads = (lambda: be.read_json(heads_path, {}) or {}) if heads_path else _read_heads
    if not be.exists(log_path):
        heads = _heads().get(name)
        if heads and heads.get("count", 0) > 0:
            return {"log": name, "ok": False, "count": 0, "exists": False,
                    "break": {"reason": "log missing but heads records "
                              f"{heads['count']} event(s) — whole-log deletion"}}
        return {"log": name, "ok": True, "count": 0, "exists": False, "detail": "no log yet"}

    prev = GENESIS_HASH
    count = 0
    for i, line in enumerate(be.read_raw(log_path)):
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            return {"log": name, "ok": False, "count": count,
                    "break": {"index": i, "reason": "line is not valid JSON"}}
        if ev.get("prev_hash") != prev:
            return {"log": name, "ok": False, "count": count,
                    "break": {"index": i, "event_id": ev.get("event_id"),
                              "reason": "prev_hash does not link to the previous "
                                        "event (reorder, insertion, or deletion)"}}
        if hash_event(ev) != ev.get("hash"):
            return {"log": name, "ok": False, "count": count,
                    "break": {"index": i, "event_id": ev.get("event_id"),
                              "reason": "content hash mismatch (event was modified)"}}
        prev = ev["hash"]
        count += 1

    result = {"log": name, "ok": True, "count": count, "exists": True, "head": prev}
    heads = _heads().get(name)
    if heads:
        if heads.get("count") != count or heads.get("head") != prev:
            result["ok"] = False
            result["break"] = {"reason": f"heads anchor mismatch — recorded "
                               f"{heads.get('count')} event(s) ending {str(heads.get('head'))[:12]}…, "
                               f"log has {count} ending {prev[:12]}… (truncation or rollback)"}
    else:
        result["head_anchor"] = "absent (cannot detect trailing truncation)"
    return result


def read_log(log_path: str | None = None) -> list[dict]:
    """Every event in a log (default: the active model's change log), oldest first."""
    return storage.get().read_lines(log_path or _p("EDITS_LOG"))


def verify_audit(logs: tuple[str, ...] | None = None) -> dict:
    """Verify every audit log. overall.ok is True only if all chains are intact."""
    if logs is None:
        logs = (_p("EDITS_LOG"), _p("EVENTS_LOG"))
    results = [verify_log(p) for p in logs]
    return {"ok": all(r["ok"] for r in results), "logs": results}


def log_action(g: Graph, task_id: str, action: str, outcome: str,
               guardrail_version: str, actor: str = "agent.kyc_verifier",
               detail: dict | None = None) -> str:
    """Append an immutable, hash-chained action event (§04: agent cites the
    guardrail version it acted under) and return a compact ack. Also the raw feed
    the signal layer aggregates in §06."""
    event = _append_event(_p("EVENTS_LOG"), {
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
    })
    return f"logged: {event['event_id']}\ntask: {task_id}\ncited_gr: {guardrail_version}"


def append_edit_event(entity_type: str, entity_id: str, op: str,
                      from_version: int | None, to_version: int,
                      actor: dict, payload: dict, reason: str,
                      log_path: str | None = None, check_version: bool = True) -> dict:
    """Append an immutable, hash-chained change-control event (ISO 9001 §7.5).
    This is the write path Phase-2 governance edits go through — a new version,
    never an overwrite. Returns the event.

    Optimistic concurrency (D50): the write is refused with ConflictError when
    `from_version` is no longer the record's current version — someone else
    saved first — so no edit silently overwrites another."""
    if log_path is None:
        log_path = _p("EDITS_LOG")   # resolve live (respects the active model)
    return _append_event(log_path, {
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
    }, expect=(entity_type, entity_id, from_version, op) if check_version else None)


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
