"""
Approval-gate workflow — Phase 3 (Core Model §07/§09, ISO 9001 §7.5 + §8.5.6).

Some changes shouldn't go live the moment one person clicks Save. This adds a
*review gate* on top of the existing audited write path: a change is submitted
as a **proposal** (a Change Request) that does NOT touch the live model; it sits
in a queue until a reviewer **approves** it (which applies it through the SAME
tested, versioned, hash-chained store method) or **rejects** it (no model
change). The proposer can **withdraw** their own pending request.

Design (deliberately additive — the direct-edit path is untouched):
  - Proposals live in their own hash-chained log, data/proposals.log.jsonl, folded
    the same event-sourced way the graph is. A proposal never mutates the graph;
    only approval does, and only through GovernanceStore (so every schema check,
    referential-integrity check, version bump and §7.5 trail still applies).
  - Any write method on the store can be gated — the op name is whitelisted and
    the arguments are shape-checked against the method's real signature at
    propose time, so a malformed or unknown op is refused before it can queue.
  - Segregation of duties is recorded, not silently enforced: if the reviewer is
    the proposer the decision is still allowed (so a one-person team can operate)
    but flagged self_approved in the audit trail.
  - If the model moved on and a stale proposal no longer applies cleanly, approve
    surfaces the store's own rejection reason and leaves the request pending.
"""
from __future__ import annotations

import inspect
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

from store import EditError  # noqa: E402

# Write methods on GovernanceStore that may be routed through the gate. Reads are
# excluded by omission. All of these share the (…domain args…, actor, reason)
# shape (edit_guardrail also takes reviewer), so one generic dispatch fits all.
PROPOSABLE_OPS = {
    "edit_guardrail", "edit_task", "add_task", "move_task", "remove_task",
    "bind_agent", "unbind_agent", "add_process", "edit_process",
    "add_role", "edit_role", "remove_role",
    "add_group", "edit_group", "remove_group",
    "edit_enterprise", "edit_objective", "edit_kpi",
    "add_initiative", "edit_initiative", "remove_initiative",
    "set_correlation", "clear_correlation",
    "add_gateway", "edit_gateway", "remove_gateway",
    "add_event", "edit_event", "remove_event",
    "add_flow", "remove_flow", "edit_flow", "enable_branching",
}

# Injected by the gate at apply time — never accepted from the caller's args.
_INJECTED = {"actor", "reason", "reviewer"}


class ApprovalError(ValueError):
    """A rejected proposal/decision — the reason is safe to show in the UI."""


def _proposals_log() -> str:
    return os.path.join(os.path.dirname(cc.EDITS_LOG), "proposals.log.jsonl")


class ApprovalQueue:
    """Folds the proposals log into the current state of every Change Request."""

    def __init__(self, store, log_path: str | None = None):
        self.store = store
        self.log_path = log_path or _proposals_log()

    # --- helpers -----------------------------------------------------------
    def _method(self, op: str):
        if op not in PROPOSABLE_OPS:
            raise ApprovalError(f"'{op}' is not an approvable change")
        return getattr(self.store, op)

    def _domain_params(self, op: str):
        """The method's own arguments, minus the ones the gate injects."""
        params = inspect.signature(self._method(op)).parameters
        return params, [n for n in params if n not in _INJECTED]

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

    def _fold(self) -> dict:
        """Latest state per Change Request id, in creation order."""
        crs: dict[str, dict] = {}
        for ev in self._events():
            cid = ev["cr_id"]
            if ev["kind"] == "propose":
                crs[cid] = {
                    "id": cid, "op": ev["op"], "args": ev["args"],
                    "title": ev.get("title", ""), "target": ev.get("target", ""),
                    "proposed_by": ev["proposed_by"], "reason": ev["reason"],
                    "proposed_at": ev["ts"], "status": "pending",
                    "decision": None,
                }
            elif cid in crs:  # decide / withdraw
                cr = crs[cid]
                cr["status"] = ev["status"]
                cr["decision"] = {
                    "status": ev["status"], "by": ev.get("by", ""),
                    "reason": ev.get("decision_reason", ""), "at": ev["ts"],
                    "self_approved": ev.get("self_approved", False),
                    "applied": ev.get("applied"),
                    "error": ev.get("error"),
                }
        return crs

    def _append(self, event: dict) -> dict:
        event["event_id"] = "cr_evt_" + cc._ulidish()
        event["ts"] = cc.datetime.now(cc.timezone.utc).isoformat()
        return cc._append_event(self.log_path, event)

    # --- reads -------------------------------------------------------------
    def list(self, status: str | None = None) -> list[dict]:
        crs = list(self._fold().values())
        crs.reverse()  # newest first
        if status:
            crs = [c for c in crs if c["status"] == status]
        return crs

    def get(self, cr_id: str) -> dict:
        cr = self._fold().get(cr_id)
        if cr is None:
            raise ApprovalError(f"unknown change request {cr_id}")
        return cr

    def pending_count(self) -> int:
        return sum(1 for c in self._fold().values() if c["status"] == "pending")

    # --- writes ------------------------------------------------------------
    def propose(self, op: str, args: dict, proposed_by: str, reason: str,
                title: str = "", target: str = "") -> dict:
        """Queue a change without touching the model. Validates the op and the
        SHAPE of the args against the real method signature, so a bad request is
        refused up front — but full schema/referential checks run at apply time."""
        if not reason or not reason.strip():
            raise ApprovalError("a change reason is required (ISO 9001 §7.5)")
        if not proposed_by or not proposed_by.startswith("role."):
            raise ApprovalError("proposer must be a role (e.g. role.ops.support_lead)")
        if not isinstance(args, dict):
            raise ApprovalError("args must be an object")
        params, domain = self._domain_params(op)
        bad = set(args) - set(domain)
        if bad:
            raise ApprovalError(f"unexpected argument(s) for {op}: {sorted(bad)}")
        missing = [n for n in domain
                   if params[n].default is inspect._empty and n not in args]
        if missing:
            raise ApprovalError(f"{op} needs: {missing}")
        cr_id = "cr_" + cc._ulidish()
        self._append({
            "kind": "propose", "cr_id": cr_id, "op": op, "args": args,
            "title": title or op, "target": target,
            "proposed_by": proposed_by, "reason": reason.strip(),
        })
        return self.get(cr_id)

    def approve(self, cr_id: str, reviewer: str, decision_reason: str = "") -> dict:
        """Apply a pending request through the real audited store method."""
        cr = self.get(cr_id)
        if cr["status"] != "pending":
            raise ApprovalError(f"request is already {cr['status']}")
        if not reviewer or not reviewer.startswith("role."):
            raise ApprovalError("reviewer must be a role (e.g. role.qms.iso_advisor)")
        method = self._method(cr["op"])
        params = inspect.signature(method).parameters
        call = dict(cr["args"])
        call["actor"] = cr["proposed_by"]
        call["reason"] = f"{cr['reason']} [approved by {reviewer}]"
        if "reviewer" in params:              # guardrail edits record the approver
            call["reviewer"] = reviewer
        call = {k: v for k, v in call.items() if k in params}
        try:
            result = method(**call)
        except (EditError, TypeError, KeyError, ValueError) as exc:
            # stale or now-invalid proposal — surface it, keep the request pending
            raise ApprovalError(f"could not apply: {exc}") from exc
        applied = self._summarize(result)
        self._append({
            "kind": "decide", "cr_id": cr_id, "status": "approved",
            "by": reviewer, "decision_reason": decision_reason.strip(),
            "self_approved": reviewer == cr["proposed_by"], "applied": applied,
        })
        return self.get(cr_id)

    def reject(self, cr_id: str, reviewer: str, decision_reason: str) -> dict:
        cr = self.get(cr_id)
        if cr["status"] != "pending":
            raise ApprovalError(f"request is already {cr['status']}")
        if not reviewer or not reviewer.startswith("role."):
            raise ApprovalError("reviewer must be a role")
        if not decision_reason or not decision_reason.strip():
            raise ApprovalError("a reason is required to reject a change")
        self._append({
            "kind": "decide", "cr_id": cr_id, "status": "rejected",
            "by": reviewer, "decision_reason": decision_reason.strip(),
        })
        return self.get(cr_id)

    def withdraw(self, cr_id: str, actor: str, decision_reason: str = "") -> dict:
        cr = self.get(cr_id)
        if cr["status"] != "pending":
            raise ApprovalError(f"request is already {cr['status']}")
        if actor != cr["proposed_by"]:
            raise ApprovalError("only the proposer can withdraw a request")
        self._append({
            "kind": "decide", "cr_id": cr_id, "status": "withdrawn",
            "by": actor, "decision_reason": decision_reason.strip(),
        })
        return self.get(cr_id)

    @staticmethod
    def _summarize(result):
        """A compact, JSON-safe note of what the applied op produced."""
        if isinstance(result, dict):
            keep = {k: result[k] for k in ("id", "version", "status") if k in result}
            return keep or {"ok": True}
        if isinstance(result, list):
            return {"count": len(result)}
        return {"ok": True}
