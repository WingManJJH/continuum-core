"""Move file-based models into Postgres, history intact (D48).

    python db/import_files.py                    # default model + every data/models/<slug>
    python db/import_files.py --only msft-bpc    # one model
    python db/import_files.py --dry-run

Copies, per model directory: every JSON document (seed.json, model.json,
layout.json, portal.json, audit_heads.json, legal_holds.json …) and every JSONL
log line **byte-for-byte**, so each hash chain re-verifies in Postgres exactly as
it did on disk. Refuses a workspace that already has history (never merges two
histories); verifies every chained log after the copy.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import storage  # noqa: E402

CHAINED = {"edits.log.jsonl", "events.log.jsonl", "proposals.log.jsonl", "approval-policy.log.jsonl"}


def model_dirs(only: str | None = None) -> list[tuple[str, str]]:
    out = [("default", cc.DATA_ROOT)]
    if os.path.isdir(cc.MODELS_DIR):
        out += [(s, os.path.join(cc.MODELS_DIR, s)) for s in sorted(os.listdir(cc.MODELS_DIR))
                if os.path.isdir(os.path.join(cc.MODELS_DIR, s))]
    return [m for m in out if not only or m[0] == only]


def import_dir(pg: storage.PostgresBackend, slug: str, base: str, dry: bool = False) -> dict:
    from psycopg.types.json import Jsonb
    ws = storage.workspace_of(os.path.join(base, "seed.json"))[0]
    docs = [f for f in sorted(os.listdir(base)) if f.endswith(".json") and os.path.isfile(os.path.join(base, f))]
    logs = [f for f in sorted(os.listdir(base)) if f.endswith(".jsonl") and os.path.isfile(os.path.join(base, f))]
    report = {"model": slug, "workspace": ws, "docs": docs, "logs": {}, "verified": {}}
    with pg.tx(ws) as c:
        n = c.execute("select count(*) from node_events where workspace_id=%s", (ws,)).fetchone()[0]
        if n:
            raise SystemExit(f"workspace {ws} already has {n} log lines in Postgres — refusing to merge histories")
        if dry:
            for lg in logs:
                with open(os.path.join(base, lg)) as f:
                    report["logs"][lg] = sum(1 for ln in f if ln.strip())
            return report
        pg._ensure_ws(c, ws)
        for d in docs:
            with open(os.path.join(base, d)) as f:
                try:
                    body = json.load(f)
                except json.JSONDecodeError:
                    continue
            c.execute("""insert into docs (workspace_id, name, body) values (%s,%s,%s)
                         on conflict (workspace_id, name) do update set body=excluded.body, updated_at=now()""",
                      (ws, d, Jsonb(body)))
            if d == "model.json":
                c.execute("update workspaces set name=%s, description=%s, source=%s, registered=true, slug=%s where id=%s",
                          (body.get("name") or slug, body.get("description") or "", body.get("source") or "", slug, ws))
        for lg in logs:
            count = 0
            with open(os.path.join(base, lg)) as f:
                for line in f:
                    raw = line.strip()
                    if not raw:
                        continue
                    ev = json.loads(raw)
                    pg._insert(c, ws, lg, raw, ev, lg in CHAINED or "hash" in ev)
                    count += 1
            report["logs"][lg] = count
        pg._reproject(c, ws)
    for lg in logs:
        if lg in CHAINED:
            with cc.use_model(slug):
                report["verified"][lg] = cc.verify_log(os.path.join(base, lg))["ok"]
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CONTINUUM_DATABASE_URL"))
    ap.add_argument("--only")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if not a.url:
        print("set CONTINUUM_DATABASE_URL or pass --url", file=sys.stderr)
        return 2
    pg = storage.PostgresBackend(a.url)
    storage.use(pg)
    ok = True
    try:
        for slug, base in model_dirs(a.only):
            r = import_dir(pg, slug, base, a.dry_run)
            good = all(r["verified"].values())
            ok &= good
            print(f"{'DRY ' if a.dry_run else ''}{slug:<14} -> {r['workspace']:<14} docs {len(r['docs'])}  "
                  + "  ".join(f"{k} {v}" for k, v in r["logs"].items())
                  + ("" if a.dry_run else f"  chains {'verified' if good else 'BROKEN'}"))
    finally:
        pg.close()  # close the pool before interpreter shutdown (no PythonFinalizationError on 3.14)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
