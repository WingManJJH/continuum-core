"""Off-box anchor tests (Phase-3+ hardening). Isolated temp dir; touches no real
audit state. Proves the anchor catches the co-forgery the D9 chain alone cannot.

    python3 test_anchor.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import anchor  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    tmp = tempfile.mkdtemp()
    cc.DATA = os.path.join(tmp, "seed.json")          # only its dirname is used
    cc.EVENTS_LOG = os.path.join(tmp, "events.log.jsonl")
    cc.EDITS_LOG = os.path.join(tmp, "edits.log.jsonl")
    cc.HEADS_FILE = os.path.join(tmp, "audit_heads.json")
    anchor.ANCHORED_LOGS = (cc.EDITS_LOG, cc.EVENTS_LOG)
    notary = anchor.LocalNotary(os.path.join(tmp, "anchors.jsonl"))

    def append(n):
        for i in range(n):
            cc._append_event(cc.EVENTS_LOG, {
                "event_id": f"evt_{i:026d}", "ts": "2026-09-01T00:00:00Z",
                "entity_type": "Task", "entity_id": "CO.3.2.7.t3", "op": "update",
                "to_version": 3, "actor": {"kind": "agent", "id": "agent.kyc_verifier"},
                "reason": "t", "payload": {"action": "verify_document", "outcome": "success",
                                           "guardrail_version": "gr.CO.3.2.7.v3"}})

    def rebuild_consistent(log):
        """Rewrite the log as an internally-consistent chain AND fix the heads —
        exactly the D9-defeating co-forgery. Mutates event 0 so the chain differs."""
        evs = [json.loads(l) for l in open(log) if l.strip()]
        evs[0]["payload"]["outcome"] = "FORGED"
        prev = cc.GENESIS_HASH
        for e in evs:
            e.pop("hash", None)
            e["prev_hash"] = prev
            e["hash"] = cc.hash_event(e)
            prev = e["hash"]
        open(log, "w").write("\n".join(json.dumps(e) for e in evs) + "\n")
        cc._write_head(log, prev, len(evs))

    # 1. anchor a 3-event chain, verify it matches
    append(3)
    rec = anchor.anchor_now(notary)
    check("anchor_now produces a signed record", "hmac" in rec and rec["combined_head"])
    r = anchor.verify_against_anchor(notary)
    check("fresh anchor verifies", r["status"] == "verified" and r["ok"])

    # 2. legitimate growth -> stale (not tampering)
    append(2)
    r = anchor.verify_against_anchor(notary)
    check("chain growth reads as stale, not tampered", r["status"] == "stale" and r["ok"])

    # 3. re-anchor -> verified again
    anchor.anchor_now(notary)
    check("re-anchor restores verified", anchor.verify_against_anchor(notary)["status"] == "verified")

    # 4. THE key test: a consistent co-forgery (log + heads both rewritten) that the
    #    D9 chain check passes, but the anchor catches via the signed prefix.
    rebuild_consistent(cc.EVENTS_LOG)
    check("D9 chain check alone PASSES the forgery (shows why anchor is needed)",
          cc.verify_log(cc.EVENTS_LOG)["ok"])
    r = anchor.verify_against_anchor(notary)
    check("anchor DETECTS the consistent co-forgery", r["status"] == "TAMPERED" and not r["ok"])

    # 5. forged anchor record (head changed, not re-signed) -> bad signature
    os.remove(notary.path)
    append(0)  # no-op; ensure clean
    # rebuild a clean chain + fresh anchor, then tamper the anchor file
    os.remove(cc.EVENTS_LOG); cc._drop_head(cc.EVENTS_LOG); append(3); anchor.anchor_now(notary)
    a = notary.latest(); a["combined_head"] = "0" * 64
    open(notary.path, "w").write(json.dumps(a) + "\n")
    r = anchor.verify_against_anchor(notary)
    check("tampered anchor record fails signature", r["status"] == "TAMPERED" and "signature" in r["detail"])

    # 6. wrong key -> signature invalid
    os.remove(notary.path); anchor.anchor_now(notary)
    saved = anchor.KEY
    anchor.KEY = b"a-different-key"
    r = anchor.verify_against_anchor(notary)
    anchor.KEY = saved
    check("wrong notary key fails verification", r["status"] == "TAMPERED")

    # 7. no anchor -> graceful
    os.remove(notary.path)
    check("no anchor yet is handled", anchor.verify_against_anchor(notary)["status"] == "no_anchor")

    # 8. ExternalNotary is declared but refuses (auth-gated, not faked)
    try:
        anchor.ExternalNotary().publish({})
        check("ExternalNotary refuses without provisioning", False)
    except RuntimeError:
        check("ExternalNotary refuses without provisioning", True)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
