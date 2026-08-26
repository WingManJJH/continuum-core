"""
End-to-end agent scenario, driven through the real MCP call_tool path.

This is the "validate the token budgets against a real agent rather than an
estimate" step (Core Model §13 step 2). It walks one agent through the exact
tool loop a bound KYC verifier would run — fetch context, check the guardrail
for each candidate action, act, log — and prints the tokenized size of every
real MCP tool response, so the §08 budgets are measured on the wire, not on the
core functions in isolation.

    python3 scenario.py
"""
from __future__ import annotations

import asyncio

import tiktoken

import server  # the MCPServer instance with the three tools

ENC = tiktoken.get_encoding("o200k_base")


def toks(s: str) -> int:
    return len(ENC.encode(s))


async def call(name: str, args: dict) -> str:
    res = await server.mcp.call_tool(name, args)
    return res.content[0].text


BUDGET = {"get_task_context": 200, "check_guardrail": 40, "log_action": 60}  # 200 per DECISIONS.md D1


async def main() -> None:
    print("=" * 74)
    print("AGENT SCENARIO — KYC verifier (agent.kyc_verifier) on task CO.3.2.7.t3")
    print("driven through MCPServer.call_tool; token counts are on the wire")
    print("=" * 74)

    steps = [
        ("1. Agent fetches its task context",
         "get_task_context", {"task_id": "CO.3.2.7.t3"}),
        ("2. Low-risk doc: may I verify? (expect ALLOW)",
         "check_guardrail", {"task_id": "CO.3.2.7.t3", "action": "verify_document",
                             "facts": {"risk_score": 0.2, "fields": ["customer.kyc_doc"]}}),
        ("3. High-risk doc: may I verify? (expect ESCALATE)",
         "check_guardrail", {"task_id": "CO.3.2.7.t3", "action": "verify_document",
                             "facts": {"risk_score": 0.9}}),
        ("4. May I approve a credit limit? (expect DENY: forbidden)",
         "check_guardrail", {"task_id": "CO.3.2.7.t3", "action": "approve_credit_limit",
                             "facts": {}}),
        ("5. May I delete the customer? (expect DENY: not on allow-list)",
         "check_guardrail", {"task_id": "CO.3.2.7.t3", "action": "delete_customer",
                             "facts": {}}),
        ("6. Touch a field outside scope? (expect DENY: out_of_scope)",
         "check_guardrail", {"task_id": "CO.3.2.7.t3", "action": "verify_document",
                             "facts": {"fields": ["customer.credit_history"]}}),
        ("7. Agent verifies the low-risk doc and logs it (cites gr version)",
         "log_action", {"task_id": "CO.3.2.7.t3", "action": "verify_document",
                        "outcome": "success", "guardrail_version": "gr.CO.3.2.7.v3"}),
    ]

    worst = {}
    for title, tool, args in steps:
        out = await call(tool, args)
        n = toks(out)
        worst[tool] = max(worst.get(tool, 0), n)
        print(f"\n{title}")
        print(f"  -> {tool}  [{n} tokens]")
        for line in out.splitlines():
            print(f"     {line}")

    print("\n" + "=" * 74)
    print("PER-TOOL PEAK vs. §08 BUDGET")
    print("-" * 74)
    ok = True
    for tool, budget in BUDGET.items():
        n = worst.get(tool, 0)
        status = "PASS" if n <= budget else "FAIL"
        ok &= n <= budget
        print(f"  {tool:<20} peak {n:>3} / {budget:<3}  {status}")
    print("=" * 74)
    print("RESULT:", "loop fits the budget on the wire" if ok else "BUDGET EXCEEDED")
    print("(events appended to ../data/events.log.jsonl — inspect the audit trail)")


if __name__ == "__main__":
    asyncio.run(main())
