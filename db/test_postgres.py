"""Postgres backend contract (D48–D50). Needs CONTINUUM_DATABASE_URL (a throwaway
database; tests/run_all.py sets it from CONTINUUM_TEST_DATABASE_URL).

    python3 db/test_postgres.py

Covers what the replayed suites can't: byte-identical hashes across backends,
tamper / truncation detection inside Postgres, the append-only trigger,
optimistic concurrency under real thread contention, per-request model isolation,
the nodes/edges projection and traversal, row-level security as a second line,
and moving file-based history into Postgres intact.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import threading
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "mcp_server"))
sys.path.insert(0, os.path.join(ROOT, "governance"))
sys.path.insert(0, HERE)

import continuum_core as cc  # noqa: E402
import storage  # noqa: E402

PASS, FAIL = [], []
URL = os.environ.get("CONTINUUM_DATABASE_URL")
ACTOR = "role.ops.support_lead"


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}" + (f"  — {detail}" if detail and not cond else ""))


def raises(exc, fn, *a, **kw):
    try:
        fn(*a, **kw)
        return False
    except exc:
        return True
    except Exception as e:  # noqa: BLE001
        return isinstance(e, exc)


class TempModel:
    """A private model directory (own workspace in Postgres) seeded from data/seed.json."""

    def __init__(self):
        self.dir = tempfile.mkdtemp()
        shutil.copy(os.path.join(ROOT, "data", "seed.json"), os.path.join(self.dir, "seed.json"))
        self.saved = (cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE)

    def __enter__(self):
        cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE = (
            os.path.join(self.dir, n) for n in ("seed.json", "edits.log.jsonl", "events.log.jsonl", "audit_heads.json"))
        return self

    def __exit__(self, *a):
        cc.DATA, cc.EDITS_LOG, cc.EVENTS_LOG, cc.HEADS_FILE = self.saved
        shutil.rmtree(self.dir, ignore_errors=True)

    @property
    def ws(self):
        return storage.workspace_of(os.path.join(self.dir, "seed.json"))[0]


def fixed_events(n=5):
    return [{"event_id": f"evt_{i:026d}", "ts": f"2026-10-01T00:00:0{i}+00:00", "entity_type": "Task",
             "entity_id": "CO.3.2.7.t3", "op": "update", "to_version": 1, "reason": "t — ünïcødé ✓",
             "actor": {"kind": "agent", "id": "agent.kyc_verifier"}, "payload": {"risk": 0.85, "n": i, "f": [1.5, None]}}
            for i in range(n)]


def main():
    if not URL:
        print("CONTINUUM_DATABASE_URL not set")
        sys.exit(2)
    pg = storage.get()
    check("backend is Postgres", pg.kind == "postgres")
    import psycopg
    # The "DBA" who can bypass triggers is the owner; the suites themselves may run as
    # the least-privilege app role (D59) when CONTINUUM_TEST_DATABASE_OWNER_URL is set.
    OWNER = os.environ.get("CONTINUUM_TEST_DATABASE_OWNER_URL") or URL
    admin = psycopg.connect(OWNER, autocommit=True)

    # 1. identical chains on both backends
    with TempModel() as m:
        fb = storage.FileBackend()
        fpath = os.path.join(tempfile.mkdtemp(), "events.log.jsonl")
        for ev in fixed_events():
            fb.append_chained(fpath, dict(ev), fpath + ".heads")
            cc._append_event(cc.EVENTS_LOG, dict(ev))
        fh = [json.loads(x)["hash"] for x in fb.read_raw(fpath)]
        ph = [e["hash"] for e in cc.read_log(cc.EVENTS_LOG)]
        check("same events -> byte-identical hash chain on file and Postgres", fh == ph and len(ph) == 5)
        v = cc.verify_log(cc.EVENTS_LOG)
        check("chain verifies in Postgres (heads anchor included)", v["ok"] and v["count"] == 5)

        # 2. append-only trigger
        check("UPDATE on node_events is refused", raises(psycopg.Error, admin.execute,
              "update node_events set raw = raw where workspace_id=%s", (m.ws,)))
        check("DELETE on node_events is refused", raises(psycopg.Error, admin.execute,
              "delete from node_events where workspace_id=%s", (m.ws,)))

        # 2b. the app role (D59): RLS isolates workspaces, and the trigger still refuses edits
        if OWNER != URL:
            app = psycopg.connect(URL, autocommit=False)
            role = app.execute("select current_user, rolbypassrls from pg_roles where rolname=current_user").fetchone()
            check("suites run as a non-owner role without BYPASSRLS", role[0] != "continuum" and not role[1])
            with app.transaction():
                n_none = app.execute("select count(*) from node_events").fetchone()[0]
            check("app role with no workspace set sees no log rows", n_none == 0)
            with app.transaction():
                app.execute("select set_config('continuum.workspace', %s, true)", ("someone-else",))
                n_other = app.execute("select count(*) from node_events where workspace_id=%s", (m.ws,)).fetchone()[0]
            check("app role scoped to another workspace cannot read this one", n_other == 0)
            with app.transaction():
                app.execute("select set_config('continuum.workspace', %s, true)", (m.ws,))
                n_own = app.execute("select count(*) from node_events where workspace_id=%s and log='events.log.jsonl'", (m.ws,)).fetchone()[0]
            check("app role scoped to its workspace reads its own log", n_own == 5)
            def _scoped(sql_):
                with app.transaction():
                    app.execute("select set_config('continuum.workspace', %s, true)", (m.ws,))
                    app.execute(sql_, (m.ws,))
            check("app role: UPDATE on its own log is refused", raises(psycopg.Error, _scoped,
                  "update node_events set raw = raw where workspace_id=%s"))
            check("app role: DELETE on its own log is refused", raises(psycopg.Error, _scoped,
                  "delete from node_events where workspace_id=%s"))
            check("app role cannot bypass the trigger", raises(psycopg.Error, _scoped,
                  "select set_config('session_replication_role', 'replica', true), %s"))
            def _cross():
                with app.transaction():
                    app.execute("select set_config('continuum.workspace', %s, true)", ("someone-else",))
                    app.execute("insert into docs (workspace_id, name, body) values (%s, 'x.json', '{}')", (m.ws,))
            check("app role cannot write into another workspace (RLS with check)", raises(psycopg.Error, _cross))
            app.close()

        # 3. tamper detection still works for someone who bypasses the trigger (DBA)
        with admin.transaction():
            admin.execute("set local session_replication_role = replica")
            admin.execute("""update node_events set raw = replace(raw, '"n": 2', '"n": 9')
                             where workspace_id=%s and log='events.log.jsonl' and seq=3""", (m.ws,))
        v = cc.verify_log(cc.EVENTS_LOG)
        check("an edited row is detected (content hash mismatch)", not v["ok"] and "hash mismatch" in v["break"]["reason"])
        with admin.transaction():
            admin.execute("set local session_replication_role = replica")
            admin.execute("""update node_events set raw = replace(raw, '"n": 9', '"n": 2')
                             where workspace_id=%s and log='events.log.jsonl' and seq=3""", (m.ws,))
            admin.execute("delete from node_events where workspace_id=%s and log='events.log.jsonl' and seq=5", (m.ws,))
        v = cc.verify_log(cc.EVENTS_LOG)
        check("a removed last row is detected (heads anchor)", not v["ok"] and "heads anchor" in v["break"]["reason"])

    # 4. optimistic concurrency
    import store as gov
    with TempModel():
        s = gov.GovernanceStore()
        base = s.guardrail("gr.CO.3.2.7")
        s.edit_guardrail("gr.CO.3.2.7", {"escalate_if": "risk_score > 0.8"}, actor=ACTOR, reason="first", reviewer=ACTOR)
        new = dict(base, version=base["version"] + 1, escalate_if="risk_score > 0.7")
        check("a write from a stale version raises ConflictError",
              raises(cc.ConflictError, cc.append_edit_event, "GuardrailPolicy", base["id"], "update",
                     base["version"], base["version"] + 1, {"kind": "human", "id": ACTOR}, new, "stale"))
        check("…and writes nothing", s.guardrail("gr.CO.3.2.7")["escalate_if"] == "risk_score > 0.8")

        # real contention: 12 threads race to edit the same record from the same read
        cur = s.guardrail("gr.CO.3.2.7")
        results = []
        barrier = threading.Barrier(12)

        def worker(i):
            body = dict(cur, version=cur["version"] + 1, escalate_if=f"risk_score > 0.{i + 10}")
            barrier.wait()
            try:
                cc.append_edit_event("GuardrailPolicy", cur["id"], "update", cur["version"], cur["version"] + 1,
                                     {"kind": "human", "id": ACTOR}, body, f"race {i}")
                results.append("ok")
            except cc.ConflictError:
                results.append("conflict")

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        check("12 concurrent editors: exactly one wins, eleven get a conflict",
              results.count("ok") == 1 and results.count("conflict") == 11, str(results))
        check("chain intact after the race", cc.verify_log(cc.EDITS_LOG)["ok"])
        vers = [e["to_version"] for e in cc.read_log() if e["entity_id"] == "gr.CO.3.2.7"]
        check("no version number was written twice", len(vers) == len(set(vers)), str(vers))

        # 5. projection + traversal
        ws = storage.workspace_of(cc.DATA)[0]
        row = admin.execute("select version, attrs->>'escalate_if' from nodes where workspace_id=%s and id=%s",
                            (ws, "gr.CO.3.2.7")).fetchone()
        g = cc.Graph().get("GuardrailPolicy", "gr.CO.3.2.7")
        check("nodes projection = the folded graph", row[0] == g["version"] and row[1] == g["escalate_if"])
        n_nodes = admin.execute("select count(*) from nodes where workspace_id=%s", (ws,)).fetchone()[0]
        seed = json.load(open(cc.DATA))
        check("every seed entity is projected", n_nodes == sum(len(v) for v in seed.values() if isinstance(v, list)))
        anc = {r[0] for r in admin.execute("select id from node_ancestors(%s, %s, 3)", (ws, "CO.3.2.7")).fetchall()}
        check("node_ancestors walks *_ref edges (tasks point at their process)", "CO.3.2.7.t3" in anc)
        des = {r[0] for r in admin.execute("select id from node_descendants(%s, %s, 2)", (ws, "CO.3.2.7.t3")).fetchall()}
        check("node_descendants walks to process + guardrail", {"CO.3.2.7", "gr.CO.3.2.7"} <= des, str(des))
        cc.reset_log(cc.EDITS_LOG)
        row = admin.execute("select version, source from nodes where workspace_id=%s and id=%s",
                            (ws, "gr.CO.3.2.7")).fetchone()
        check("reset re-projects from the seed", row == (base["version"], "seed"))

    # 6. per-request model isolation (two users, two models, same process)
    with TempModel() as a, TempModel() as b:
        sa, sb = os.path.join(a.dir), os.path.join(b.dir)
        cc.MODELS_DIR, saved_md = tempfile.mkdtemp(), cc.MODELS_DIR
        try:
            for slug, src in (("alpha", sa), ("beta", sb)):
                os.makedirs(cc.model_base(slug))
                storage.get().write_json(os.path.join(cc.model_base(slug), "seed.json"), json.load(open(os.path.join(src, "seed.json"))))
                storage.get().write_json(os.path.join(cc.model_base(slug), "model.json"), {"name": slug.title(), "source": "test", "description": ""})
            check("registered models are listed from Postgres", {"alpha", "beta"} <= {x["slug"] for x in cc.list_models()})
            errs = []

            def edit(slug, n):
                try:
                    with cc.use_model(slug, user={"email": f"{slug}@example.com"}):
                        for i in range(n):
                            gr = cc.Graph().get("GuardrailPolicy", "gr.CO.3.2.7")
                            body = dict(gr, version=gr["version"] + 1, escalate_if=f"{slug} {i}")
                            cc.append_edit_event("GuardrailPolicy", gr["id"], "update", gr["version"], body["version"],
                                                 {"kind": "human", "id": ACTOR}, body, f"{slug} edit")
                except Exception as e:  # noqa: BLE001
                    errs.append(repr(e))

            t1, t2 = threading.Thread(target=edit, args=("alpha", 6)), threading.Thread(target=edit, args=("beta", 4))
            t1.start(), t2.start(), t1.join(), t2.join()
            with cc.use_model("alpha"):
                ea = cc.read_log()
            with cc.use_model("beta"):
                eb = cc.read_log()
            check("two models edited concurrently from one process: no cross-talk",
                  not errs and len(ea) == 6 and len(eb) == 4
                  and all(e["payload"]["escalate_if"].startswith("alpha") for e in ea)
                  and all(e["payload"]["escalate_if"].startswith("beta") for e in eb), str(errs[:1]))
            check("each event names the signed-in user", all(e["actor"].get("user") == "alpha@example.com" for e in ea))
            check("outside a request the process default is untouched", cc.ACTIVE_MODEL == "default")
        finally:
            cc.MODELS_DIR = saved_md

    # 7. row-level security as a second line
    role = "continuum_rls_" + uuid.uuid4().hex[:8]
    try:
        admin.execute(f"create role {role} login password 'x'")
        admin.execute(f"grant select, insert, update, delete on workspaces, docs, node_events, nodes, edges to {role}")
        admin.execute(f"grant usage, select on all sequences in schema public to {role}")
        info = psycopg.conninfo.conninfo_to_dict(URL)
        info.update(user=role, password="x")
        with psycopg.connect(**info) as conn:
            total = admin.execute("select count(distinct workspace_id) from nodes").fetchone()[0]
            conn.execute("select set_config('continuum.workspace', 'default', false)")
            seen = {r[0] for r in conn.execute("select distinct workspace_id from nodes").fetchall()}
            check("RLS: a non-owner session sees only its workspace", seen <= {"default"} and total > 1, f"{seen}")
            conn.execute("select set_config('continuum.workspace', '', false)")
            check("RLS: no workspace set -> no rows", conn.execute("select count(*) from nodes").fetchone()[0] == 0)
            try:
                conn.execute("insert into docs (workspace_id, name, body) values ('other', 'x', '{}')")
                leaked = True
            except psycopg.Error:
                leaked = False
                conn.rollback()
            check("RLS: cannot write into another workspace", not leaked)
    finally:
        admin.execute(f"drop owned by {role}")
        admin.execute(f"drop role if exists {role}")

    # 8. moving file history into Postgres intact
    import import_files
    with tempfile.TemporaryDirectory() as tmpm:
        saved = (storage.get(), cc.MODELS_DIR)
        storage.use(storage.FileBackend())
        cc.MODELS_DIR = tmpm
        try:
            base = cc.model_base("legacy")
            os.makedirs(base)
            shutil.copy(os.path.join(ROOT, "data", "seed.json"), os.path.join(base, "seed.json"))
            json.dump({"name": "Legacy", "source": "files", "description": ""}, open(os.path.join(base, "model.json"), "w"))
            with cc.use_model("legacy"):
                s = gov.GovernanceStore()
                for i in range(3):
                    s.edit_guardrail("gr.CO.3.2.7", {"escalate_if": f"risk_score > 0.{i + 5}"}, actor=ACTOR,
                                     reason=f"file edit {i}", reviewer=ACTOR)
                file_heads = storage.get().read_json(os.path.join(base, "audit_heads.json"))
                file_fold = cc.Graph().get("GuardrailPolicy", "gr.CO.3.2.7")
            storage.use(saved[0])
            r = import_files.import_dir(saved[0], "legacy", base)
            check("file history imported; every chain verifies in Postgres", r["logs"].get("edits.log.jsonl") == 3
                  and all(r["verified"].values()), str(r))
            with cc.use_model("legacy"):
                check("same heads and same folded state after the move",
                      storage.get().read_json(os.path.join(base, "audit_heads.json")) == file_heads
                      and cc.Graph().get("GuardrailPolicy", "gr.CO.3.2.7") == file_fold)
            check("re-import is refused (never merges two histories)",
                  raises(SystemExit, import_files.import_dir, saved[0], "legacy", base))
        finally:
            storage.use(saved[0])
            cc.MODELS_DIR = saved[1]

    admin.close()
    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
