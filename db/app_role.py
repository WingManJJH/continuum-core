"""Create or update the least-privilege login Continuum runs as (D59).

    python db/app_role.py --url <owner URL>            # prompts for the new app password
    python db/app_role.py --url <owner URL> --check    # report only, change nothing

Run it with the database OWNER (on Supabase: the `postgres` user). It is safe to
re-run: every statement is idempotent, and re-running only resets the password.

What `continuum_app` gets — and nothing more:
  * LOGIN, with no superuser, createdb, createrole, replication or BYPASSRLS
  * SELECT/INSERT/UPDATE/DELETE on the Continuum tables, USAGE on their sequences
  * the same on tables the owner creates later (default privileges), so a new
    migration doesn't silently lock the app out
It never owns a table, so the row-level-security policies from 0003 apply to it.

On Supabase this also revokes the platform's default grants to `anon`,
`authenticated` and `service_role` on the Continuum tables: the Data API is off, but nothing other
than Continuum should be able to reach these rows.
"""
from __future__ import annotations

import argparse
import getpass
import os
import sys

ROLE = "continuum_app"
TABLES = ("workspaces", "docs", "node_events", "nodes", "edges")
API_ROLES = ("anon", "authenticated", "service_role")  # Supabase Data API roles (service_role bypasses RLS)


def ensure(conn, password: str) -> list[str]:
    from psycopg import sql
    done = []
    exists = conn.execute("select 1 from pg_roles where rolname=%s", (ROLE,)).fetchone()
    verb = "alter" if exists else "create"
    conn.execute(sql.SQL("{} role {} with login nosuperuser nocreatedb nocreaterole noreplication "
                         "nobypassrls password {}").format(sql.SQL(verb), sql.Identifier(ROLE),
                                                           sql.Literal(password)))
    done.append(f"{verb}{'d' if verb == 'create' else 'ed'} role {ROLE}")
    db = conn.execute("select current_database()").fetchone()[0]
    owner = conn.execute("select current_user").fetchone()[0]
    ident = sql.Identifier
    conn.execute(sql.SQL("grant connect on database {} to {}").format(ident(db), ident(ROLE)))
    conn.execute(sql.SQL("grant usage on schema public to {}").format(ident(ROLE)))
    tables = [t for t in TABLES if conn.execute("select to_regclass(%s)", ("public." + t,)).fetchone()[0]]
    if len(tables) != len(TABLES):
        raise SystemExit(f"missing tables {sorted(set(TABLES) - set(tables))}: run db/migrate.py first")
    conn.execute(sql.SQL("grant select, insert, update, delete on {} to {}").format(
        sql.SQL(", ").join(ident(t) for t in tables), ident(ROLE)))
    conn.execute(sql.SQL("grant usage, select on all sequences in schema public to {}").format(ident(ROLE)))
    conn.execute(sql.SQL("alter default privileges for role {} in schema public "
                         "grant select, insert, update, delete on tables to {}").format(ident(owner), ident(ROLE)))
    conn.execute(sql.SQL("alter default privileges for role {} in schema public "
                         "grant usage, select on sequences to {}").format(ident(owner), ident(ROLE)))
    done.append(f"granted DML on {', '.join(tables)} (+ future tables of {owner})")
    for r in API_ROLES:
        if conn.execute("select 1 from pg_roles where rolname=%s", (r,)).fetchone():
            conn.execute(sql.SQL("revoke all on {} from {}").format(
                sql.SQL(", ").join(ident(t) for t in tables), ident(r)))
            done.append(f"revoked {r} on the Continuum tables")
    return done


def check(conn) -> tuple[bool, list[str]]:
    """Every line is a fact about the live database; ok is False if any is wrong."""
    out, ok = [], True
    row = conn.execute("""select rolcanlogin, rolsuper, rolbypassrls, rolcreaterole, rolcreatedb
                          from pg_roles where rolname=%s""", (ROLE,)).fetchone()
    if not row:
        return False, [f"{ROLE}: missing"]
    login, sup, bypass, crole, cdb = row
    good = login and not (sup or bypass or crole or cdb)
    ok &= good
    out.append(f"{ROLE}: login={login} superuser={sup} bypassrls={bypass} createrole={crole} createdb={cdb}"
               + ("" if good else "  <-- WRONG"))
    for t in TABLES:
        owner, rls = conn.execute("""select pg_get_userbyid(c.relowner), c.relrowsecurity from pg_class c
                                     where c.oid = to_regclass(%s)""", ("public." + t,)).fetchone()
        privs = [p for p in ("select", "insert", "update", "delete")
                 if conn.execute("select has_table_privilege(%s, %s, %s)", (ROLE, "public." + t, p)).fetchone()[0]]
        good = owner != ROLE and len(privs) == 4 and (rls or t == "workspaces")
        ok &= good
        out.append(f"  {t:<12} owner={owner:<10} rls={'on ' if rls else 'off'} app={','.join(privs) or '-'}"
                   + ("" if good else "  <-- WRONG"))
    for r in API_ROLES:
        if conn.execute("select 1 from pg_roles where rolname=%s", (r,)).fetchone():
            leaks = [t for t in TABLES if conn.execute(
                "select has_table_privilege(%s, %s, 'select')", (r, "public." + t)).fetchone()[0]]
            ok &= not leaks
            out.append(f"  {r}: " + (f"can read {', '.join(leaks)}  <-- WRONG" if leaks else "no access"))
    return ok, out


def main(argv=None) -> int:
    import psycopg
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("CONTINUUM_DATABASE_URL"), help="owner connection")
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    if not a.url:
        print("pass --url (the owner connection) or set CONTINUUM_DATABASE_URL", file=sys.stderr)
        return 2
    with psycopg.connect(a.url) as conn:
        if not a.check:
            pw = os.environ.get("CONTINUUM_APP_PASSWORD") or getpass.getpass(f"New password for {ROLE}: ")
            if not os.environ.get("CONTINUUM_APP_PASSWORD") and pw != getpass.getpass("Again: "):
                print("passwords differ; nothing changed", file=sys.stderr)
                return 1
            if len(pw) < 16:
                print("use at least 16 characters; nothing changed", file=sys.stderr)
                return 1
            with conn.transaction():
                for line in ensure(conn, pw):
                    print(line)
        ok, lines = check(conn)
    print("\n".join(lines))
    print("least privilege: OK" if ok else "least privilege: PROBLEMS ABOVE")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
