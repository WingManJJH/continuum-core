"""
Continuum MCP server — Phase-3 deliverable, prototyped in Phase 1 (Core Model §07).

Exposes the three purpose-built tools an agent binds to, over MCP stdio:
  - get_task_context(task_id)                         -> §03 context package
  - check_guardrail(task_id, action, facts)           -> allow / escalate / deny
  - log_action(task_id, action, outcome, gr_version)  -> immutable audit event

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

import continuum_core as cc

mcp = MCPServer("continuum")
_graph = cc.Graph()  # single hand-built graph for the prototype


@mcp.tool()
def get_task_context(task_id: str) -> str:
    """Return the complete context an agent needs to act on one task: its ids,
    inputs/outputs, KPIs, and the inline guardrail (allow/deny/escalate/scope)
    plus the model signature the agent must cite when logging an action.
    Compact by design (< 150 tokens). Example task_id: 'CO.3.2.7.t3'."""
    return cc.render_task_context(_graph, task_id)


@mcp.tool()
def check_guardrail(task_id: str, action: str, facts: dict | None = None) -> str:
    """Ask the Enforcement Point whether `action` is permitted on `task_id`
    before taking it. `facts` supplies values the escalate_if condition and the
    data-scope check read (e.g. {"risk_score": 0.9, "fields": ["customer.kyc_doc"]}).
    Returns a decision (allow / escalate / deny) with a reason code and the
    version-pinned guardrail ref to cite. < 40 tokens."""
    return cc.render_guardrail_check(
        cc.check_guardrail(_graph, task_id, action, facts or {})
    )


@mcp.tool()
def log_action(task_id: str, action: str, outcome: str,
               guardrail_version: str, actor: str = "agent.kyc_verifier") -> str:
    """Write an immutable audit event for an action just taken. The agent MUST
    pass the `guardrail_version` it acted under (the `gr:` value from
    check_guardrail / the context package) so a later dispute resolves against
    the policy that actually applied (§04). Feeds the signal layer in §06."""
    return cc.log_action(_graph, task_id, action, outcome, guardrail_version, actor)


if __name__ == "__main__":
    mcp.run()
