"""MCP tool surface (D45/D47): new Ripple / Vitals tools and live folding. Plain asserts.

    python3 mcp_server/test_server_tools.py
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import server  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    tmp = tempfile.mkdtemp()
    shutil.copy(os.path.join(HERE, "..", "data", "seed.json"), os.path.join(tmp, "seed.json"))
    saved = (cc.DATA, cc.EDITS_LOG, cc.HEADS_FILE)
    cc.DATA, cc.EDITS_LOG, cc.HEADS_FILE = (os.path.join(tmp, n) for n in ("seed.json", "edits.log.jsonl", "audit_heads.json"))
    try:
        out = server.get_impact("CO.3.2.7")
        check("get_impact summarizes reach", out.startswith("A change to ") and "CO.3.2.7.t3" in out)
        check("get_impact cites the agent's guardrail version", "gr:gr.CO.3.2.7.v3" in out)
        check("get_impact on an unknown id", server.get_impact("nope") == "unknown item")
        vt = server.get_vitals()
        check("get_vitals leads with the score", vt.startswith("score "))
        check("tool output stays compact (< 1200 chars)", len(out) < 1200 and len(vt) < 1200)
        # live fold: an edit is visible to the next tool call without a restart
        g = cc.Graph()
        gr = g.get("GuardrailPolicy", "gr.CO.3.2.7")
        new = dict(gr, version=gr["version"] + 1)
        cc.append_edit_event("GuardrailPolicy", gr["id"], "update", gr["version"], new["version"],
                             {"kind": "human", "id": "role.ops.support_lead"}, new, "test bump")
        check("agents see a saved edit immediately (no restart)", "gr.CO.3.2.7.v4" in server.get_task_context("CO.3.2.7.t3"))
    finally:
        cc.DATA, cc.EDITS_LOG, cc.HEADS_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
