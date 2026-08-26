"""
Enforcement Point — Phase 3 (Core Model §04 Figure 3, §09 Phase 3, §11).

The generic gate every agent action passes through. It holds NO policy of its
own — it reads the Guardrail Policy on the current step (via continuum_core) and:

    allow    → execute the underlying tool, then log success
    escalate → do NOT execute; enqueue for a human, log the escalation
    deny     → do NOT execute; log the refusal
    rate     → over the policy's rate_limit → deny before even checking, log it

The one invariant that makes this real rather than advisory: the underlying tool
callable is invoked ONLY on an allow decision. An agent cannot reach the tool
except through act(); this is the "MCP server is the only sanctioned path" policy
of §11, enforced in code. Every outcome writes to the same immutable audit log
(events.log.jsonl) that the signal layer / conformance check (§06) reads.

Rate limiting is now stateful (per agent, per guardrail, sliding window) — the
Phase-1 note that it was "not enforced in the stateless prototype" is closed here.
"""
from __future__ import annotations

import json
import os
import sys
from collections import defaultdict, deque
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

ESCALATIONS = os.path.join(os.path.dirname(cc.DATA), "escalations.jsonl")


class EnforcementPoint:
    def __init__(self, graph: cc.Graph | None = None, tools: dict | None = None):
        self.g = graph or cc.Graph()
        # action name -> callable(facts) -> result. The ONLY place tools live.
        self.tools: dict[str, callable] = tools or {}
        self._history: dict[tuple, deque] = defaultdict(deque)  # (actor, gr_id) -> [ts]

    def register(self, action: str, fn) -> None:
        self.tools[action] = fn

    def act(self, task_id: str, action: str, actor: str,
            facts: dict | None = None) -> dict:
        facts = facts or {}
        gr, pinned = self.g.effective_guardrail(task_id)

        # 1. rate limit — contain a looping/misbehaving agent before any policy work
        if gr and gr.get("rate_limit") and self._rate_exceeded(actor, gr):
            cc.log_action(self.g, task_id, action, "rate_limited", pinned, actor=actor,
                          detail={"limit": gr["rate_limit"]})
            return {"status": "denied", "reason": "rate_limited", "gr": pinned}

        # 2. policy decision — the EP reads, it does not decide
        v = cc.check_guardrail(self.g, task_id, action, facts)
        dec = v["decision"]

        if dec == "allow":
            self._record(actor, gr)
            result = self.tools[action](facts) if action in self.tools else None
            cc.log_action(self.g, task_id, action, "success", v["gr"], actor=actor,
                          detail={"result": result})
            return {"status": "executed", "result": result, "gr": v["gr"]}

        if dec == "escalate":
            self._enqueue(task_id, action, actor, v, facts)
            cc.log_action(self.g, task_id, action, "escalated", v["gr"], actor=actor,
                          detail={"to": v.get("to")})
            return {"status": "escalated", "to": v.get("to"), "gr": v["gr"]}

        # deny — tool never runs
        cc.log_action(self.g, task_id, action, "denied", v["gr"], actor=actor,
                      detail={"reason": v["reason"]})
        return {"status": "denied", "reason": v["reason"], "gr": v["gr"]}

    # --- rate limiting (sliding window) ------------------------------------
    def _rate_exceeded(self, actor: str, gr: dict) -> bool:
        rl = gr["rate_limit"]
        key = (actor, gr["id"])
        now = datetime.now(timezone.utc).timestamp()
        window = self._history[key]
        while window and now - window[0] > rl["per_seconds"]:
            window.popleft()
        return len(window) >= rl["max_actions"]

    def _record(self, actor: str, gr: dict | None) -> None:
        if gr and gr.get("rate_limit"):
            self._history[(actor, gr["id"])].append(
                datetime.now(timezone.utc).timestamp())

    # --- escalation queue --------------------------------------------------
    def _enqueue(self, task_id, action, actor, verdict, facts) -> None:
        rec = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "task": task_id, "action": action, "agent": actor,
            "assigned_to": verdict.get("to"), "gr": verdict["gr"],
            "reason": verdict["reason"], "facts": facts, "status": "open",
        }
        with open(ESCALATIONS, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def escalation_queue(self) -> list[dict]:
        if not os.path.exists(ESCALATIONS):
            return []
        with open(ESCALATIONS) as f:
            return [json.loads(x) for x in f if x.strip()]
