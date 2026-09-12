"""Audit-log hash-chain tests (Phase 3+ hardening). Plain asserts; uses a
temp log so it never touches real audit state.

    python3 test_audit_chain.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def read(path):
    return [l for l in open(path).read().splitlines() if l.strip()]


def write(path, lines):
    open(path, "w").write("\n".join(lines) + "\n")


def main():
    tmp = tempfile.mkdtemp()
    log = os.path.join(tmp, "events.log.jsonl")
    # point the heads file into the temp dir so the real one is untouched
    cc.HEADS_FILE = os.path.join(tmp, "audit_heads.json")

    def append(n):
        for i in range(n):
            ev = cc._append_event(log, {
                "event_id": f"evt_{i:026d}", "ts": "2026-08-26T00:00:00Z",
                "entity_type": "Task", "entity_id": "CO.3.2.7.t3", "op": "update",
                "to_version": 3, "actor": {"kind": "agent", "id": "agent.kyc_verifier"},
                "reason": "test", "payload": {"action": "verify_document", "outcome": "success",
                                              "guardrail_version": "gr.CO.3.2.7.v3"}})

    # 1. a fresh chain of 5 events verifies intact, heads anchor matches
    append(5)
    r = cc.verify_log(log)
    check("intact chain verifies ok", r["ok"] and r["count"] == 5)
    check("first event links to genesis", read(log) and json.loads(read(log)[0])["prev_hash"] == cc.GENESIS_HASH)
    check("each event carries a hash + prev_hash", all(
        set(("hash", "prev_hash")) <= set(json.loads(l)) for l in read(log)))

    # 2. content tamper (edit a field in the middle) → content hash mismatch
    lines = read(log)
    ev = json.loads(lines[2]); ev["payload"]["outcome"] = "TAMPERED"; lines[2] = json.dumps(ev)
    write(log, lines)
    r = cc.verify_log(log)
    check("content tamper detected", not r["ok"] and "content hash mismatch" in r["break"]["reason"])
    check("content tamper located at the edited event (#2)", r["break"]["index"] == 2)

    # rebuild clean for the next cases
    os.remove(log); os.remove(cc.HEADS_FILE); append(5)

    # 3. deletion of a middle event → next event's prev_hash no longer links
    lines = read(log); del lines[2]; write(log, lines)
    r = cc.verify_log(log)
    check("deletion detected (prev_hash link broken)", not r["ok"] and "prev_hash" in r["break"]["reason"])

    os.remove(log); os.remove(cc.HEADS_FILE); append(5)

    # 4. reorder two events → prev_hash link broken
    lines = read(log); lines[1], lines[2] = lines[2], lines[1]; write(log, lines)
    r = cc.verify_log(log)
    check("reorder detected", not r["ok"] and "prev_hash" in r["break"]["reason"])

    os.remove(log); os.remove(cc.HEADS_FILE); append(5)

    # 5. trailing truncation (drop last 2 lines, leave heads) → heads anchor mismatch
    lines = read(log); write(log, lines[:-2])
    r = cc.verify_log(log)
    check("trailing truncation detected via heads anchor",
          not r["ok"] and "heads anchor mismatch" in r["break"]["reason"])

    os.remove(log)  # heads still records 5 events, log now gone
    # 6. whole-log deletion → heads knows events existed
    r = cc.verify_log(log)
    check("whole-log deletion detected via heads", not r["ok"] and "whole-log deletion" in r["break"]["reason"])

    # 7. verify_audit rolls up multiple logs
    os.remove(cc.HEADS_FILE)
    append(3)
    edits = os.path.join(tmp, "edits.log.jsonl")
    cc._append_event(edits, {"event_id": "evt_x", "ts": "2026-08-26T00:00:00Z",
                             "entity_type": "GuardrailPolicy", "entity_id": "gr.CO.3.2.7",
                             "op": "update", "to_version": 4,
                             "actor": {"kind": "human", "id": "role.ops.support_lead"},
                             "reason": "e", "payload": {}})
    roll = cc.verify_audit((edits, log))
    check("verify_audit ok when all chains intact", roll["ok"] and len(roll["logs"]) == 2)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
