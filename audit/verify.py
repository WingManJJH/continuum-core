"""
Audit-log chain verifier — ISO 9001 §7.5 tamper-evidence (Phase 3+ hardening).

Re-walks each append-only audit log and confirms the hash chain is intact:
every event's `prev_hash` links to the previous event, and every event's `hash`
matches its recomputed content. Any edit, deletion, reorder, or insertion breaks
the chain and is reported with the exact position. A per-log heads anchor
(data/audit_heads.json) additionally catches trailing truncation / rollback and
whole-log deletion.

    python3 verify.py            # human report (exit 1 if any chain is broken)
    python3 verify.py --json     # machine-readable

What this does and does not prove: it proves no event was changed, dropped, or
reordered without detection by anyone who did not also rewrite the whole chain
and the heads file in lockstep. It does not prevent a writer with full access to
both the log and the heads file from forging a fresh consistent chain — that
requires anchoring the head off-box (external notarization / append-only store),
the next hardening step. This is stated plainly, not assumed away.
"""
from __future__ import annotations

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402


def main() -> int:
    report = cc.verify_audit()
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        return 0 if report["ok"] else 1

    print("=" * 70)
    print("CONTINUUM AUDIT-LOG CHAIN VERIFICATION (ISO 9001 §7.5)")
    print("=" * 70)
    for r in report["logs"]:
        status = "INTACT" if r["ok"] else "BROKEN"
        head = r.get("head")
        headstr = f" · head {head[:12]}…" if head else ""
        print(f"\n  {r['log']:<22} {status}  · {r['count']} event(s){headstr}")
        if not r["ok"]:
            b = r.get("break", {})
            where = f"event #{b['index']}" if "index" in b else "log"
            print(f"      ✗ {where}: {b.get('reason')}")
            if b.get("event_id"):
                print(f"        event_id {b['event_id']}")
        elif r.get("head_anchor"):
            print(f"      note: heads anchor {r['head_anchor']}")
    print("\n" + "-" * 70)
    print("RESULT:", "ALL CHAINS INTACT" if report["ok"] else "TAMPERING DETECTED")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
