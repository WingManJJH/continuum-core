"""Retention-policy engine tests (§7.5.3). Isolated temp dir. Proves the schedule,
legal holds, deliberate/logged disposition, review-never-auto, and that the live
hash-chained logs are never mutated.

    python3 test_retention.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import retention as ret  # noqa: E402

PASS, FAIL = [], []
AS_OF = datetime(2026, 9, 13, tzinfo=timezone.utc)


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    tmp = tempfile.mkdtemp()
    cc.DATA = os.path.join(tmp, "seed.json")
    cc.EVENTS_LOG = os.path.join(tmp, "events.log.jsonl")
    cc.EDITS_LOG = os.path.join(tmp, "edits.log.jsonl")
    cc.HEADS_FILE = os.path.join(tmp, "audit_heads.json")
    LOGS = (cc.EDITS_LOG, cc.EVENTS_LOG)
    archive = os.path.join(tmp, "archive.jsonl")
    ledger = os.path.join(tmp, "ledger.jsonl")
    holds = {"HELD.entity"}

    n = [0]

    def ev(log, entity, etype, ts, payload=None):
        n[0] += 1
        cc._append_event(log, {
            "event_id": f"evt_{n[0]:026d}", "ts": ts, "entity_type": etype,
            "entity_id": entity, "op": "update", "to_version": 1,
            "actor": {"kind": "system", "id": "test"}, "reason": "t",
            "payload": payload or {}})

    # agent-action records (events.log): old due, recent not, one on legal hold
    ev(cc.EVENTS_LOG, "CO.3.2.7.t3", "Task", "2020-01-01T00:00:00Z")           # old -> due archive
    ev(cc.EVENTS_LOG, "CO.3.2.7.t3", "Task", "2026-09-01T00:00:00Z")           # recent -> not due
    ev(cc.EVENTS_LOG, "HELD.entity", "Task", "2019-01-01T00:00:00Z")           # old but HELD
    ev(cc.EVENTS_LOG, "sig.1", "Task", "2024-01-01T00:00:00Z", {"record_class": "signal_ingest"})  # old -> dispose
    # change-control records (edits.log)
    ev(cc.EDITS_LOG, "gr.CO.3.2.7", "GuardrailPolicy", "2016-01-01T00:00:00Z")  # old -> due archive
    ev(cc.EDITS_LOG, "gr.CO.3.2.7", "GuardrailPolicy", "2026-09-01T00:00:00Z")  # recent -> not due
    ev(cc.EDITS_LOG, "CO.3.2.7", "Process", "2016-01-01T00:00:00Z")            # old -> _default review

    live_events_before = len(open(cc.EVENTS_LOG).read().splitlines())
    live_edits_before = len(open(cc.EDITS_LOG).read().splitlines())

    plan = ret.evaluate(AS_OF, logs=LOGS, holds=holds)
    cls = plan["classes"]
    check("agent_action: 1 due (old), recent excluded", len(cls["agent_action"]["due"]) == 1)
    check("change.GuardrailPolicy: 1 due (7y), recent excluded", len(cls["change.GuardrailPolicy"]["due"]) == 1)
    check("signal_ingest: 1 due with dispose action", len(cls["signal_ingest"]["due"]) == 1
          and cls["signal_ingest"]["rule"]["action"] == "dispose")
    check("unmapped class falls to _default review", cls["change.Process"]["rule"]["action"] == "review"
          and len(cls["change.Process"]["due"]) == 1)
    check("legal hold exempts the held record", plan["held_total"] == 1
          and plan["held"][0]["entity"] == "HELD.entity")
    check("due_total counts all 4 due (incl. the review one)", plan["due_total"] == 4)

    res = ret.apply(AS_OF, logs=LOGS, holds=holds, archive_path=archive, ledger_path=ledger)
    check("apply archives the 3 archive/dispose records", res["archived"] == 3)
    check("apply skips the review-class record", res["skipped_review"] == 1)
    check("apply skips the held record", res["skipped_on_hold"] == 1)

    arch = [json.loads(x) for x in open(archive)]
    led = [json.loads(x) for x in open(ledger)]
    check("cold archive holds the 3 records (preserved, not destroyed)", len(arch) == 3)
    check("ledger records each disposition with actor + action", len(led) == 3
          and all(l["by"] == "role.qms.records" and l["action"] in ("archive", "dispose") for l in led))
    check("dispose ledger note flags the seal-and-roll deployment step",
          any("seal-and-roll" in l["note"] for l in led if l["action"] == "dispose"))

    # the live hash-chained logs must be untouched, and still verify
    check("live events log unchanged", len(open(cc.EVENTS_LOG).read().splitlines()) == live_events_before)
    check("live edits log unchanged", len(open(cc.EDITS_LOG).read().splitlines()) == live_edits_before)
    check("live chains still intact after disposition", cc.verify_log(cc.EVENTS_LOG)["ok"]
          and cc.verify_log(cc.EDITS_LOG)["ok"])

    # idempotent: a second apply disposes nothing new
    res2 = ret.apply(AS_OF, logs=LOGS, holds=holds, archive_path=archive, ledger_path=ledger)
    check("second apply is idempotent (0 new)", res2["archived"] == 0)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
