"""
Audit chain off-box anchor — Phase-3+ hardening (closes the D9 honest gap).

The D9 hash chain catches anyone who edits a log but not the heads file. Its stated
limit: a party who rewrites BOTH the log and the heads file can forge a consistent
chain. This module closes that by periodically ANCHORING the chain: it takes a
signed, timestamped fingerprint over BOTH logs and hands it to a notary the log
writer cannot rewrite.

  - The fingerprint (`combined_head`) is one hash over both logs' heads + counts —
    a single integrity value for the whole audit store (the "one signed store"
    idea, without merging the files).
  - It is HMAC-signed with a key held by the notary/audit role, NOT the log writer.
    An attacker who rewrites a log cannot produce a matching signed anchor without
    the key, and cannot rewrite past anchors held by the notary.
  - verify_against_anchor() re-derives each log's head at the anchored count and
    checks it still equals the anchored head (a rewritten prefix is caught), then
    checks the signature. It distinguishes fresh / stale (chain legitimately grew)
    / TAMPERED.

HONEST BOUNDARY (kept explicit): security now reduces to two things being off the
log-writer's box — the HMAC key and the append-only notary store. LocalNotary keeps
both on-box, so it is a faithful STAND-IN, not the real guarantee — exactly like the
signal-layer connectors. ExternalNotary is the auth-gated real thing (a write-once
external service / notarization). The mechanism is complete; the off-box hosting is
the deployment step.

    python3 anchor.py            # anchor the current chain, then verify
    python3 anchor.py --verify   # verify against the latest anchor only
"""
from __future__ import annotations

import hmac
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

ANCHORS_FILE = os.path.join(os.path.dirname(cc.DATA), "audit_anchors.jsonl")
# In production this key lives in the audit service / HSM, never with the log writer.
# The env var is the seam; the default is a clearly-labelled dev key.
KEY = os.environ.get("CONTINUUM_AUDIT_KEY", "dev-only-not-a-real-key").encode()
ANCHORED_LOGS = (cc.EDITS_LOG, cc.EVENTS_LOG)


# --- notary (where anchors are published; the writer must not be able to rewrite it)
class Notary:
    name = "base"

    def publish(self, record: dict) -> None:
        raise NotImplementedError

    def latest(self) -> dict | None:
        raise NotImplementedError


class LocalNotary(Notary):
    """Stand-in: appends anchors to a local file. Faithful for the mechanism, but
    on the same box as the logs, so not the real off-box guarantee (see module doc)."""
    name = "local"

    def __init__(self, path: str = ANCHORS_FILE):
        self.path = path

    def publish(self, record: dict) -> None:
        with open(self.path, "a") as f:
            f.write(json.dumps(record) + "\n")

    def latest(self) -> dict | None:
        if not os.path.exists(self.path):
            return None
        last = None
        with open(self.path) as f:
            for line in f:
                if line.strip():
                    last = line
        return json.loads(last) if last else None


class ExternalNotary(Notary):
    """The real thing: a write-once external notarization service. Auth-gated and
    unavailable in this build — declared, not faked (cf. signal/connectors.py)."""
    name = "external"

    def publish(self, record: dict) -> None:
        raise RuntimeError("ExternalNotary requires an external append-only "
                           "notarization service (auth-gated, unavailable in this build). "
                           "LocalNotary stands in; swap this in once provisioned.")

    latest = publish  # same gate


# --- signing / fingerprint -------------------------------------------------
def _canonical(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _sign(record_without_sig: dict) -> str:
    return hmac.new(KEY, _canonical(record_without_sig).encode(), "sha256").hexdigest()


def _head_at(log_path: str, n: int) -> str | None:
    """Chain head after exactly `n` valid events, verifying the chain as it walks.
    None if the log has fewer than n events or the chain breaks before n."""
    if n == 0:
        return cc.GENESIS_HASH
    prev = cc.GENESIS_HASH
    seen = 0
    if not os.path.exists(log_path):
        return None
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            ev = json.loads(line)
            if ev.get("prev_hash") != prev or cc.hash_event(ev) != ev.get("hash"):
                return None
            prev = ev["hash"]
            seen += 1
            if seen == n:
                return prev
    return None


def _current_entries() -> list[dict]:
    entries = []
    for p in ANCHORED_LOGS:
        r = cc.verify_log(p)
        entries.append({"log": os.path.basename(p),
                        "head": r.get("head", cc.GENESIS_HASH),
                        "count": r.get("count", 0)})
    return entries


def _combined(entries: list[dict]) -> str:
    import hashlib
    joined = "|".join(f"{e['log']}:{e['head']}:{e['count']}" for e in sorted(entries, key=lambda e: e["log"]))
    return hashlib.sha256(joined.encode()).hexdigest()


# --- public API ------------------------------------------------------------
def anchor_now(notary: Notary | None = None) -> dict:
    """Take a signed fingerprint of the current chain and publish it to the notary."""
    notary = notary or LocalNotary()
    entries = _current_entries()
    rec = {"ts": datetime.now(timezone.utc).isoformat(),
           "entries": entries, "combined_head": _combined(entries)}
    rec["hmac"] = _sign(rec)
    notary.publish(rec)
    return rec


def verify_against_anchor(notary: Notary | None = None) -> dict:
    """Check the live chain against the latest notarized anchor.
    status: no_anchor | verified | stale (chain grew, re-anchor) | TAMPERED."""
    notary = notary or LocalNotary()
    anchor = notary.latest()
    if not anchor:
        return {"status": "no_anchor", "ok": True,
                "detail": "no anchor yet — run anchor_now() to establish a baseline"}

    # 1. authenticity: the anchor itself must be signed with the notary key
    body = {k: v for k, v in anchor.items() if k != "hmac"}
    if not hmac.compare_digest(_sign(body), anchor.get("hmac", "")):
        return {"status": "TAMPERED", "ok": False,
                "detail": "anchor signature invalid — anchor forged or wrong key"}

    # 2. integrity: each anchored prefix must still hash to the anchored head
    grew = False
    for e in anchor["entries"]:
        path = os.path.join(os.path.dirname(cc.DATA), e["log"])
        prefix_head = _head_at(path, e["count"])
        if prefix_head != e["head"]:
            return {"status": "TAMPERED", "ok": False,
                    "detail": f"{e['log']}: anchored prefix no longer matches — the "
                              f"first {e['count']} event(s) were rewritten or removed"}
        live = cc.verify_log(path)
        if not live["ok"]:
            return {"status": "TAMPERED", "ok": False,
                    "detail": f"{e['log']}: live chain broken ({live.get('break', {}).get('reason')})"}
        if live.get("count", 0) > e["count"]:
            grew = True

    if grew:
        return {"status": "stale", "ok": True,
                "detail": "anchored prefix intact; chain has grown since — re-anchor to cover new events",
                "anchor_ts": anchor["ts"]}
    return {"status": "verified", "ok": True,
            "detail": "live chain matches the notarized anchor exactly", "anchor_ts": anchor["ts"]}


if __name__ == "__main__":
    if "--verify" not in sys.argv:
        rec = anchor_now()
        print(f"anchored at {rec['ts']}  combined_head {rec['combined_head'][:16]}...  "
              f"({', '.join(f'{e['log']}:{e['count']}' for e in rec['entries'])})")
    r = verify_against_anchor()
    print(f"verify vs anchor: {r['status'].upper()} — {r['detail']}")
    sys.exit(0 if r["ok"] else 1)
