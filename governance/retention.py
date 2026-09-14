"""
Retention-policy engine — ISO 9001 §7.5.3 retention & disposition (Phase-3+ hardening).

The audit trail keeps everything; §7.5 also requires a defined retention period and
a deliberate disposition schedule per record class — the last flagged hardening piece
(the `deprecate` op existed; a scheduler did not). This is that scheduler.

What it does:
  - classifies every audit record (both logs) into a retention class,
  - against a rule table (retain period + disposition action), reports what is DUE,
  - honors LEGAL HOLDS — a held entity's records are never dispositioned, whatever
    their age,
  - `apply()` performs the disposition deliberately and auditably: it copies due
    records to an append-only cold ARCHIVE and writes a disposition LEDGER entry per
    record. It NEVER removes records from the live hash-chained logs, so tamper-
    evidence is preserved, and it NEVER auto-destroys — `review`-class records are
    surfaced for a human and left alone.

HONEST BOUNDARY (kept explicit): physically *removing* an expired record from a
hash-chained log without breaking the chain requires sealing the old prefix and
re-basing the live log on a new genesis (a "seal-and-roll", anchored via
audit/anchor.py) — a deployment-grade operation, out of scope here. So a `dispose`
action archives + ledgers the decision and marks the seal-and-roll as the remaining
step; it does not shred the chained copy. Nothing is lost, nothing is silently
destroyed, and the schedule + legal-hold + auditable-disposition requirements of
§7.5 are met.

    python3 retention.py            # print the disposition plan
    python3 retention.py --apply    # archive + ledger the due, non-held records
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

DATA_DIR = os.path.dirname(cc.DATA)
ARCHIVE = os.path.join(DATA_DIR, "audit_archive.jsonl")
LEDGER = os.path.join(DATA_DIR, "retention_ledger.jsonl")
LEGAL_HOLDS_FILE = os.path.join(DATA_DIR, "legal_holds.json")

# retain period (days) + disposition action per record class.
#   archive  -> move to cold store, keep (records are never destroyed)
#   dispose  -> archive + record intent; physical shred is the seal-and-roll step
#   review   -> surface for a human; never auto-dispositioned
RETENTION_RULES = {
    "agent_action":          {"retain_days": 1095, "action": "archive"},   # 3y
    "change.GuardrailPolicy": {"retain_days": 2555, "action": "archive"},   # 7y — compliance-critical
    "signal_ingest":         {"retain_days": 365,  "action": "dispose"},    # 1y — raw ingest
    "_default":              {"retain_days": 2555, "action": "review"},
}


def legal_holds() -> set[str]:
    """Entity ids exempt from disposition (litigation / audit hold)."""
    if not os.path.exists(LEGAL_HOLDS_FILE):
        return set()
    try:
        with open(LEGAL_HOLDS_FILE) as f:
            return set(json.load(f))
    except (json.JSONDecodeError, OSError):
        return set()


def record_class(ev: dict, log_path: str) -> str:
    override = ev.get("payload", {}).get("record_class")
    if override:
        return override
    if os.path.basename(log_path) == os.path.basename(cc.EVENTS_LOG):
        return "agent_action"
    return "change." + ev.get("entity_type", "Unknown")


def _parse(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _read(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def evaluate(as_of: datetime | None = None,
             logs: tuple[str, ...] = (cc.EDITS_LOG, cc.EVENTS_LOG),
             holds: set[str] | None = None) -> dict:
    as_of = as_of or datetime.now(timezone.utc)
    holds = holds if holds is not None else legal_holds()
    classes: dict[str, dict] = {}
    held: list[dict] = []

    for log in logs:
        for ev in _read(log):
            cls = record_class(ev, log)
            rule = RETENTION_RULES.get(cls, RETENTION_RULES["_default"])
            age = (as_of - _parse(ev["ts"])).days
            c = classes.setdefault(cls, {"rule": rule, "total": 0, "due": [], "oldest_age": 0})
            c["total"] += 1
            c["oldest_age"] = max(c["oldest_age"], age)
            if age >= rule["retain_days"]:
                rec = {"id": ev["event_id"], "entity": ev.get("entity_id"),
                       "age_days": age, "action": rule["action"], "log": os.path.basename(log)}
                if ev.get("entity_id") in holds:
                    held.append({**rec, "reason": "legal_hold"})
                else:
                    c["due"].append(rec)

    due_total = sum(len(c["due"]) for c in classes.values())
    return {"as_of": as_of.isoformat(), "classes": classes,
            "held": held, "due_total": due_total, "held_total": len(held),
            "holds": sorted(holds)}


def apply(as_of: datetime | None = None, actor: str = "role.qms.records",
          logs: tuple[str, ...] = (cc.EDITS_LOG, cc.EVENTS_LOG),
          holds: set[str] | None = None,
          archive_path: str = ARCHIVE, ledger_path: str = LEDGER) -> dict:
    """Disposition due, non-held records deliberately: copy to the cold archive and
    write a ledger entry. Never touches the live chained logs; never auto-destroys
    (`review` records are skipped). Idempotent — already-ledgered records are skipped."""
    as_of = as_of or datetime.now(timezone.utc)
    already = {e["record_id"] for e in _read(ledger_path)}
    # index the live events so we can archive the full record by id
    events = {}
    for log in logs:
        for ev in _read(log):
            events[ev["event_id"]] = (ev, os.path.basename(log))

    plan = evaluate(as_of, logs, holds)
    now = datetime.now(timezone.utc).isoformat()
    archived, disposed_ids = 0, []
    for cls, c in plan["classes"].items():
        action = c["rule"]["action"]
        if action == "review":
            continue  # human-only; never auto-dispositioned
        for rec in c["due"]:
            if rec["id"] in already:
                continue
            ev, logname = events[rec["id"]]
            with open(archive_path, "a") as f:  # cold store — records preserved, not destroyed
                f.write(json.dumps({**ev, "_archived_at": now, "_class": cls, "_action": action,
                                    "_from_log": logname}) + "\n")
            with open(ledger_path, "a") as f:
                f.write(json.dumps({
                    "record_id": rec["id"], "entity": rec["entity"], "class": cls,
                    "action": action, "disposed_at": now, "by": actor,
                    "note": ("physical removal from the chained log is the seal-and-roll "
                             "deployment step; the chained copy is preserved")
                            if action == "dispose" else "archived to cold store",
                }) + "\n")
            archived += 1
            disposed_ids.append(rec["id"])
    return {"archived": archived, "ids": disposed_ids,
            "skipped_on_hold": plan["held_total"],
            "skipped_review": sum(len(c["due"]) for cl, c in plan["classes"].items()
                                  if c["rule"]["action"] == "review")}


if __name__ == "__main__":
    plan = evaluate()
    print("=" * 70)
    print("CONTINUUM RETENTION PLAN (ISO 9001 §7.5.3) — as of", plan["as_of"][:10])
    print("=" * 70)
    for cls, c in sorted(plan["classes"].items()):
        r = c["rule"]
        print(f"  {cls:<26} {c['total']:>4} records · retain {r['retain_days']}d · "
              f"{r['action']:<8} · {len(c['due'])} due · oldest {c['oldest_age']}d")
    print(f"\n  due for disposition: {plan['due_total']}   ·   on legal hold (exempt): {plan['held_total']}")
    if plan["held"]:
        for h in plan["held"]:
            print(f"    HELD  {h['entity']}  ({h['age_days']}d, would be {h['action']})")
    print("  disposition is deliberate + logged; review-class records are surfaced, never auto-applied")
    if "--apply" in sys.argv:
        res = apply()
        print(f"\n  APPLIED: archived+ledgered {res['archived']} record(s); "
              f"skipped {res['skipped_on_hold']} on hold, {res['skipped_review']} review-only")
