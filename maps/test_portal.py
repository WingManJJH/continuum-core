"""Publish-portal tests (Phase E). Plain asserts.

Uses a temp portal file so it never touches real data/portal.json.

    python3 test_portal.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import portal  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def main():
    tmp = tempfile.mkdtemp()
    portal.PORTAL_PATH = os.path.join(tmp, "portal.json")

    # 1. mint a link for a real process
    rec = portal.publish("CO.3.2.7", "Customer onboarding", "role.ops.support_lead")
    check("publish returns a token", bool(rec["token"]) and len(rec["token"]) >= 10)
    check("token is unguessable (url-safe, no spaces)", " " not in rec["token"] and "/" not in rec["token"])
    check("record captures target + title + author + model_sig",
          rec["target"] == "CO.3.2.7" and rec["title"] == "Customer onboarding"
          and rec["created_by"] == "role.ops.support_lead" and bool(rec["model_sig"]))

    # 2. resolve the token to a read-only process view
    view = portal.portal_view(rec["token"])
    check("portal_view resolves kind=process", view is not None and view["kind"] == "process")
    check("view carries that process's tasks + owner (read shape)",
          view["process"]["id"] == "CO.3.2.7" and len(view["process"]["tasks"]) >= 1
          and view["process"]["owner"].startswith("role."))
    check("view meta reports current=True right after publish", view["meta"]["current"] is True)

    # 3. unknown target refused; bad author refused
    try:
        portal.publish("ZZ.9.9.9", "nope", "role.x"); ok = False
    except ValueError:
        ok = True
    check("publishing an unknown process is refused", ok)
    try:
        portal.publish("CO.3.2.7", "t", "not-a-role"); ok = False
    except ValueError:
        ok = True
    check("a link must be attributed to a role", ok)

    # 4. landscape target
    lrec = portal.publish(portal.LANDSCAPE_TARGET, "Org landscape", "role.ops.support_lead")
    lview = portal.portal_view(lrec["token"])
    check("landscape link resolves kind=landscape",
          lview["kind"] == "landscape" and lview["landscape"]["processes_total"] == 8)

    # 5. unknown token -> None
    check("unknown token resolves to None", portal.portal_view("does-not-exist") is None)

    # 6. revoke kills the link
    check("revoke returns True the first time", portal.revoke(rec["token"]) is True)
    check("revoked token no longer resolves", portal.portal_view(rec["token"]) is None)
    check("revoke is idempotent (False second time)", portal.revoke(rec["token"]) is False)

    # 7. expiry is enforced
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    erec = portal.publish("FN.9.3.1", "expired share", "role.ops.support_lead", expires_at=past)
    check("an expired link does not resolve", portal.get(erec["token"]) is None)
    future = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    frec = portal.publish("FN.9.3.1", "future share", "role.ops.support_lead", expires_at=future)
    check("a not-yet-expired link resolves", portal.get(frec["token"]) is not None)

    # 8. manage list annotates status + staleness
    links = portal.all_links()
    check("all_links lists every minted link", len(links) == 4)
    statuses = {l["token"]: l["status"] for l in links}
    check("manage list marks revoked / expired / active",
          statuses[rec["token"]] == "revoked" and statuses[erec["token"]] == "expired"
          and statuses[lrec["token"]] == "active")

    # 9. publishing is NOT a governed-model edit (Core Model §08) — like layout,
    #    it must never mutate the graph or the audit/edit log.
    edits_before = os.path.getsize(cc.EDITS_LOG) if os.path.exists(cc.EDITS_LOG) else 0
    portal.publish("SC.4.3.6", "supply chain", "role.ops.support_lead")
    edits_after = os.path.getsize(cc.EDITS_LOG) if os.path.exists(cc.EDITS_LOG) else 0
    check("minting a link writes no governance edit event", edits_before == edits_after)
    check("portal is not a governed entity type", "Portal" not in cc.Graph()._by_type)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
