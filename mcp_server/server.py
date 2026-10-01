"""
Continuum MCP server — Phase-3 deliverable, prototyped in Phase 1 (Core Model §07).

Exposes the three purpose-built tools an agent binds to, over MCP stdio:
  - get_task_context(task_id)                         -> §03 context package
  - check_guardrail(task_id, action, facts)           -> allow / escalate / deny
  - log_action(task_id, action, outcome, gr_version)  -> immutable audit event
  - get_impact(item_id)                               -> Ripple: what a change touches (D45)
  - get_vitals()                                      -> model-health score + top findings (D45)

The server holds NO policy logic of its own — it is the generic Enforcement
Point of §04, reading whatever the Guardrail Policy object says. All decision
logic lives in continuum_core. This is the one sanctioned path to the actionable
system for any guardrailed task (§11 bypass risk).

Run as an MCP server (stdio):
    python3 server.py
Register with an MCP client (e.g. Claude Code):
    claude mcp add continuum -- python3 /abs/path/to/server.py
"""
from __future__ import annotations

from mcp.server.mcpserver import MCPServer  # MCP SDK 2.x (was FastMCP in 1.x)

import os
import sys

import continuum_core as cc

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from enterprise import rules  # noqa: E402

mcp = MCPServer("continuum")


def _g() -> cc.Graph:
    """Fold seed + change log on every call, so a governance edit is live for
    agents the moment it is saved (one source of truth). D47: the server used to
    fold once at start-up, which left agents on a stale policy until a restart."""
    return cc.Graph()


@mcp.tool()
def get_task_context(task_id: str) -> str:
    """Return the complete context an agent needs to act on one task: its ids,
    inputs/outputs, KPIs, and the inline guardrail (allow/deny/escalate/scope)
    plus the model signature the agent must cite when logging an action.
    Compact by design (< 150 tokens). Example task_id: 'CO.3.2.7.t3'."""
    return cc.render_task_context(_g(), task_id)


@mcp.tool()
def check_guardrail(task_id: str, action: str, facts: dict | None = None) -> str:
    """Ask the Enforcement Point whether `action` is permitted on `task_id`
    before taking it. `facts` supplies values the escalate_if condition and the
    data-scope check read (e.g. {"risk_score": 0.9, "fields": ["customer.kyc_doc"]}).
    Returns a decision (allow / escalate / deny) with a reason code and the
    version-pinned guardrail ref to cite. < 40 tokens."""
    return cc.render_guardrail_check(
        cc.check_guardrail(_g(), task_id, action, facts or {})
    )


@mcp.tool()
def log_action(task_id: str, action: str, outcome: str,
               guardrail_version: str, actor: str = "agent.kyc_verifier") -> str:
    """Write an immutable audit event for an action just taken. The agent MUST
    pass the `guardrail_version` it acted under (the `gr:` value from
    check_guardrail / the context package) so a later dispute resolves against
    the policy that actually applied (§04). Feeds the signal layer in §06."""
    return cc.log_action(_g(), task_id, action, outcome, guardrail_version, actor)



@mcp.tool()
def get_impact(item_id: str) -> str:
    """Ripple: what a change to a process, task, capability, system, agent,
    obligation, control or risk reaches — tasks, processes, KPIs, controls,
    obligations, and the agents (with guardrail version) whose context changes.
    Ask before proposing a change. Example item_id: 'CO.3.2.7'."""
    return render_impact(rules.ripple(rules.View(_g()), item_id))


@mcp.tool()
def get_vitals() -> str:
    """Model health: score (share of governance checks passing) and the most
    severe findings, each with the item id and what to do."""
    return render_vitals(rules.vitals(rules.View(_g())))


def render_impact(r: dict, limit: int = 12) -> str:
    if not r["start"]:
        return "unknown item"
    lines = [r["summary"]]
    for a in sorted(r["affected"], key=lambda a: (a["depth"], a["type"], a["id"]))[:limit]:
        lines.append(f"- {a['type']} {a['id']} (d{a['depth']})")
    if len(r["affected"]) > limit:
        lines.append(f"- … {len(r['affected']) - limit} more")
    for gd in r["guardrails"]:
        lines.append(f"agents on {gd['taskId']}: {', '.join(gd['agents'])} gr:{gd['version'] or 'none'}"
                     + (" UNGUARDED" if gd["blank"] else ""))
    return "\n".join(lines)


def render_vitals(v: dict, limit: int = 5) -> str:
    b = v["bySeverity"]
    lines = [f"score {v['score']} ({v['passed']}/{v['checks']}) critical {b['critical']} warning {b['warning']} info {b['info']}"]
    for f in v["findings"][:limit]:
        lines.append(f"- {f['severity']} {f['rule']} {f['nodeId'] or f['name']}: {f['message']}")
    return "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
