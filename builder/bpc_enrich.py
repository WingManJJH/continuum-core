"""
Overlay governance metadata onto imported processes with Jev (System One).

An imported Microsoft BPC model is a rich taxonomy with almost no governance data
(no risk, ownership, customer-facing flags). Jev is built for exactly this: for
each process, ask a few *typed* questions and get back typed answers in one fast,
cheap, non-hallucinating pass. Answers are written to the process's master data
through the SAME governed, versioned, audited write path (store.edit_process) —
Jev suggests, the governed model records, a human still owns the result.

Env-gated like the LLM seam: with no CONTINUUM_TYPESAFE_API_KEY and no injected
transport it refuses. A transport(state, questions) -> dict runs it hermetically.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "governance"))
import continuum_core as cc  # noqa: E402
import typesafe as ts  # noqa: E402

# The typed questions we ask about each process. All three Jev primitives, and all
# write into free-form custom{} master data (no new schema, no dangling refs).
DEFAULT_QUESTIONS = [
    {"id": "risk_level", "kind": "score", "scale": [1, 5],
     "prompt": "Operational/compliance risk if this process runs incorrectly (1 low, 5 high)."},
    {"id": "customer_facing", "kind": "noul",
     "prompt": "Is this process customer-facing (touches an external customer)?"},
    {"id": "automation_potential", "kind": "score", "scale": [1, 5],
     "prompt": "How suitable is this process for AI-agent automation (1 low, 5 high)?"},
]


def _state(p: dict) -> dict:
    c = p.get("custom", {}) or {}
    return {"id": p["id"], "name": p.get("name", ""),
            "description": c.get("description", ""),
            "product": c.get("product", ""), "sequence": c.get("bpc_seq", "")}


def enrich(store, transport=None, limit=None, actor="role.ops.support_lead",
           questions=None, dry=False) -> dict:
    """Classify each active process in the active model and write the answers to
    its custom master data. Returns a summary. Refuses if Jev is unavailable."""
    questions = questions or DEFAULT_QUESTIONS
    if not ts.available(transport):
        raise RuntimeError("no Jev access — set CONTINUUM_TYPESAFE_API_KEY (or inject a transport)")
    g = store.graph()
    procs = sorted((p for p in g.all("Process") if p["status"] == "active"), key=lambda p: p["id"])
    if limit:
        procs = procs[:limit]
    updated = 0
    for p in procs:
        ans = ts.decide(_state(p), questions, transport=transport)
        add = {
            "risk_level": ans["risk_level"]["score"],
            "customer_facing": ans["customer_facing"]["noul"] >= 0.5,
            "automation_potential": ans["automation_potential"]["score"],
            "enriched_by": "jev",
        }
        if dry:
            continue
        custom = dict(p.get("custom", {}) or {}, **add)
        store.edit_process(p["id"], {"custom": custom}, actor,
                           "Jev governance enrichment (advisory, classified)")
        updated += 1
    return {"processed": len(procs), "updated": updated, "dry": dry}


def main(argv):
    import argparse
    ap = argparse.ArgumentParser(description="Enrich an imported model's processes with Jev")
    ap.add_argument("--model", default="default", help="model slug to enrich")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--dry", action="store_true", help="classify but don't write")
    args = ap.parse_args(argv)
    sys.path.insert(0, os.path.join(HERE, "..", "governance"))
    import store as gov
    cc.set_active_model(args.model)
    res = enrich(gov.GovernanceStore(), limit=args.limit, dry=args.dry)
    print(f"model '{args.model}': processed {res['processed']}, updated {res['updated']}"
          + (" (dry run)" if res["dry"] else ""))


if __name__ == "__main__":
    main(sys.argv[1:])
