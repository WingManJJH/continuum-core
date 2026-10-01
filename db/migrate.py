"""Apply db/migrations/*.sql in order, once each (D48).

    python db/migrate.py                      # uses CONTINUUM_DATABASE_URL
    python db/migrate.py --url postgresql://… # explicit
    python db/migrate.py --status             # list applied / pending
"""
from __future__ import annotations

import argparse
import glob
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
MIGRATIONS = os.path.join(HERE, "migrations")


def files() -> list[str]:
    return sorted(glob.glob(os.path.join(MIGRATIONS, "*.sql")))


def migrate(url: str, verbose: bool = True) -> list[str]:
    import psycopg
    applied = []
    with psycopg.connect(url, autocommit=False) as conn:
        with conn.transaction():
            conn.execute("select pg_advisory_xact_lock(4242)")  # two deployers never race
            conn.execute("""create table if not exists schema_migrations (
                              version text primary key, applied_at timestamptz not null default now())""")
            done = {r[0] for r in conn.execute("select version from schema_migrations").fetchall()}
            for path in files():
                v = os.path.basename(path)
                if v in done:
                    continue
                with open(path) as f:
                    conn.execute(f.read())
                conn.execute("insert into schema_migrations (version) values (%s)", (v,))
                applied.append(v)
                if verbose:
                    print("applied", v)
    return applied


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CONTINUUM_DATABASE_URL"))
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args(argv)
    if not a.url:
        print("set CONTINUUM_DATABASE_URL or pass --url", file=sys.stderr)
        return 2
    if a.status:
        import psycopg
        with psycopg.connect(a.url) as conn:
            try:
                done = {r[0] for r in conn.execute("select version from schema_migrations").fetchall()}
            except psycopg.errors.UndefinedTable:
                done = set()
        for p in files():
            v = os.path.basename(p)
            print(("applied " if v in done else "pending ") + v)
        return 0
    n = migrate(a.url)
    print(f"{len(n)} migration(s) applied" if n else "up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
