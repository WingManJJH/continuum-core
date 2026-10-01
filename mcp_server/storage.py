"""Storage backends for the governed model (D48).

Every persisted thing in Continuum is one of two shapes, addressed by the path the
code has always used (`<model dir>/<name>`):

  * a **document** — `seed.json`, `model.json`, `layout.json`, `portal.json`,
    `audit_heads.json`, `legal_holds.json` …  (read_json / write_json)
  * an **append-only log** — `edits.log.jsonl`, `events.log.jsonl`,
    `proposals.log.jsonl` …  Chained logs (append_chained) carry prev_hash/hash;
    plain logs (append_line) are escalations, archives, ledgers.

The path's directory names the **workspace** (the default model → `default`,
`data/models/<slug>` → `<slug>`, any other directory → a stable `dir:<hash>` key)
and the file name names the record, so no caller changes its addressing and a
workspace is exactly what a model directory was.

Backends:
  FileBackend      — the original JSON / JSONL files (default; offline; tests)
  PostgresBackend  — CONTINUUM_DATABASE_URL set. Supabase-lineage schema
                     (db/migrations): workspaces, docs, node_events (every log
                     line, exact bytes kept so hashes re-verify), nodes + edges
                     (current-state projection of the change log, for
                     traversal and the concurrency check).

Both backends give the same guarantees:
  * a chained append is atomic with its heads-anchor update;
  * appends to one log are serialized across threads AND processes
    (file: flock; Postgres: advisory transaction lock);
  * optimistic concurrency — append_chained(..., expect=(type, id, from_version, op))
    refuses a write whose from_version is not the record's current version
    (ConflictError), so two editors can never silently overwrite each other.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import threading
from contextlib import contextmanager

GENESIS_HASH = "0" * 64
_HERE = os.path.dirname(os.path.abspath(__file__))
DATA_ROOT = os.path.normpath(os.path.join(_HERE, "..", "data"))
MODELS_DIR = os.path.join(DATA_ROOT, "models")
SYSTEM_DIR = os.path.join(DATA_ROOT, "_system")   # users, memberships, sign-in audit (not a model)
_DEFAULT_SYSTEM_DIR = SYSTEM_DIR                     # tests may repoint SYSTEM_DIR at a temp dir
EDITS_NAME = "edits.log.jsonl"


class ConflictError(RuntimeError):
    """The record changed since the writer read it (stale from_version)."""

    def __init__(self, entity_type, entity_id, expected, current):
        self.entity_type, self.entity_id, self.expected, self.current = entity_type, entity_id, expected, current
        super().__init__(f"{entity_type} {entity_id} changed since you opened it "
                         f"(you edited v{expected}, it is now v{current}) — reload and re-apply your change")


def canonical(event: dict) -> str:
    return json.dumps(event, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def hash_event(event: dict) -> str:
    body = {k: v for k, v in event.items() if k != "hash"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


# continuum_core points this at its live MODELS_DIR (tests repoint it)
models_dir_hook = lambda: MODELS_DIR  # noqa: E731


def workspace_of(path: str) -> tuple[str, str]:
    """(workspace key, record name) for a storage path."""
    d, name = os.path.split(os.path.normpath(os.path.abspath(path)))
    if d == DATA_ROOT:
        return "default", name
    if d == _DEFAULT_SYSTEM_DIR:
        return "_system", name
    mdir = os.path.normpath(os.path.abspath(models_dir_hook()))
    if os.path.dirname(d) == mdir:
        # a model slug — namespaced by its models dir when that is not the
        # standard one (tests point MODELS_DIR at a temp dir), so runs never collide
        return (os.path.basename(d) if mdir == MODELS_DIR
                else "dir:" + hashlib.sha1(d.encode()).hexdigest()[:16]), name
    return "dir:" + hashlib.sha1(d.encode()).hexdigest()[:16], name


def _version_status(payload, op):
    if not isinstance(payload, dict):
        return None, None
    st = payload.get("status")
    if op == "deprecate":
        st = "deprecated"
    return payload.get("version"), st


def _seed_versions(seed: dict) -> dict:
    out = {}
    for etype, rows in seed.items():
        if isinstance(rows, list):
            for r in rows:
                if isinstance(r, dict) and "id" in r:
                    out[(etype, r["id"])] = (r.get("version"), r.get("status"))
    return out


def _check_expect(current, expect):
    """current: (version, status) or None. expect: (etype, id, from_version, op)."""
    etype, eid, from_v, op = expect
    if op in ("update", "deprecate", "restore"):
        cur_v = current[0] if current else None
        if cur_v != from_v:
            raise ConflictError(etype, eid, from_v, cur_v)
    elif op == "create" and current and current[1] not in (None, "deprecated") and from_v is None:
        raise ConflictError(etype, eid, None, current[0])


# =========================================================================== file
class FileBackend:
    kind = "file"

    def __init__(self):
        self._tlock = threading.RLock()
        self._index: dict[str, dict] = {}   # edits-log path -> {"pos", "seed_sig", "versions"}

    # ---- documents
    def read_json(self, path, default=None):
        try:
            with open(path) as f:
                return json.load(f)
        except FileNotFoundError:
            return default
        except (OSError, json.JSONDecodeError):
            if default is not None:
                return default
            raise

    def write_json(self, path, obj, indent=2):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(obj, f, indent=indent)
        os.replace(tmp, path)  # atomic: a reader never sees a half-written document

    def exists(self, path) -> bool:
        return os.path.exists(path)

    def remove(self, path):
        if os.path.exists(path):
            os.remove(path)

    def size(self, path) -> int:
        try:
            return os.path.getsize(path)
        except OSError:
            return 0

    # ---- logs
    def read_lines(self, path) -> list[dict]:
        if not os.path.exists(path):
            return []
        out = []
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out

    def read_raw(self, path) -> list[str]:
        """Exact stored lines (for verification)."""
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [ln.strip() for ln in f if ln.strip()]

    @contextmanager
    def _locked(self, path):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with self._tlock, open(path + ".lock", "a") as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)   # across processes (run.py starts five apps)
            try:
                yield
            finally:
                fcntl.flock(lk, fcntl.LOCK_UN)

    def append_line(self, path, obj):
        with self._locked(path):
            with open(path, "a") as f:
                f.write(json.dumps(obj) + "\n")

    def _last_hash(self, path):
        last = None
        if os.path.exists(path):
            with open(path, "rb") as f:
                try:  # read from the end: O(1) for long logs
                    f.seek(-65536, os.SEEK_END)
                except OSError:
                    f.seek(0)
                for line in f.read().splitlines():
                    if line.strip():
                        last = line
        if not last:
            return GENESIS_HASH
        return json.loads(last).get("hash", GENESIS_HASH)

    def _current(self, log_path, seed_path, etype, eid):
        """(version, status) of a record = seed baseline + every edit, cached and
        advanced incrementally by file offset."""
        idx = self._index.get(log_path)
        try:
            st = os.stat(seed_path) if seed_path else None
            sig = (st.st_mtime_ns, st.st_ino) if st else None
        except OSError:
            sig = None
        try:
            ino = os.stat(log_path).st_ino
        except OSError:
            ino = None
        size = self.size(log_path)
        if idx is None or idx["seed_sig"] != sig or size < idx["pos"] or idx["ino"] != ino:
            seed = self.read_json(seed_path, {}) if seed_path else {}
            idx = {"seed_sig": sig, "ino": ino, "pos": 0, "versions": _seed_versions(seed)}
            self._index[log_path] = idx
        if size > idx["pos"] and os.path.exists(log_path):
            with open(log_path) as f:
                f.seek(idx["pos"])
                for line in f:
                    if line.strip():
                        ev = json.loads(line)
                        v, st = _version_status(ev.get("payload"), ev.get("op"))
                        if v is None:
                            v = ev.get("to_version")
                        idx["versions"][(ev.get("entity_type"), ev.get("entity_id"))] = (v, st)
                idx["pos"] = f.tell()
        return idx["versions"].get((etype, eid))

    def append_chained(self, path, event, heads_path, expect=None, seed_path=None):
        with self._locked(path):
            if expect is not None:
                _check_expect(self._current(path, seed_path, expect[0], expect[1]), expect)
            event["prev_hash"] = self._last_hash(path)
            event["hash"] = hash_event(event)
            with open(path, "a") as f:
                f.write(json.dumps(event) + "\n")
            heads = self.read_json(heads_path, {}) or {}
            cur = heads.get(os.path.basename(path), {})
            heads[os.path.basename(path)] = {"head": event["hash"], "count": cur.get("count", 0) + 1}
            self.write_json(heads_path, heads)
        return event

    def reset_log(self, path, heads_path):
        with self._locked(path):
            if os.path.exists(path):
                os.remove(path)
            heads = self.read_json(heads_path, {}) or {}
            if heads.pop(os.path.basename(path), None) is not None:
                self.write_json(heads_path, heads)
            self._index.pop(path, None)

    def list_workspaces(self) -> list[dict]:
        out = []
        mdir = models_dir_hook()
        if os.path.isdir(mdir):
            for slug in sorted(os.listdir(mdir)):
                m = self.read_json(os.path.join(mdir, slug, "model.json"), None)
                if m is not None:
                    out.append({"slug": slug, **m})
        return out


# =========================================================================== postgres
class PostgresBackend:
    kind = "postgres"

    def __init__(self, url: str, min_size: int = 1, max_size: int = 10):
        import psycopg  # noqa: F401  (fail fast with a clear error if not installed)
        from psycopg_pool import ConnectionPool
        self.url = url
        self.pool = ConnectionPool(url, min_size=min_size, max_size=max_size, open=True,
                                   kwargs={"autocommit": False})

    def close(self):
        self.pool.close()

    @contextmanager
    def tx(self, ws: str | None):
        with self.pool.connection() as conn:
            with conn.transaction():
                if ws is not None:
                    conn.execute("select set_config('continuum.workspace', %s, true)", (ws,))
                yield conn

    def _ensure_ws(self, conn, ws):
        conn.execute("insert into workspaces (id, name) values (%s, %s) on conflict (id) do nothing", (ws, ws))

    # ---- documents
    ADOPT = ("seed.json", "model.json")  # baselines adopted from disk on first use

    def read_json(self, path, default=None):
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            row = c.execute("select body from docs where workspace_id=%s and name=%s", (ws, name)).fetchone()
        if row is None and name in self.ADOPT and os.path.isfile(path):
            # A model baseline that exists on disk but not yet in the database
            # (first run, or a source-controlled seed): adopt it, once. Logs are
            # never adopted implicitly — db/import_files.py moves history.
            with open(path) as f:
                body = json.load(f)
            self.write_json(path, body)
            return body
        return default if row is None else row[0]

    def write_json(self, path, obj, indent=2):
        from psycopg.types.json import Jsonb
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            self._ensure_ws(c, ws)
            c.execute("""insert into docs (workspace_id, name, body, updated_at) values (%s,%s,%s,now())
                         on conflict (workspace_id, name) do update set body=excluded.body, updated_at=now()""",
                      (ws, name, Jsonb(obj)))
            if name == "seed.json":
                self._reproject(c, ws)
            if name == "model.json" and isinstance(obj, dict):
                c.execute("""update workspaces set name=%s, description=%s, source=%s, registered=true, slug=%s
                             where id=%s""", (obj.get("name") or ws, obj.get("description") or "",
                                              obj.get("source") or "", os.path.basename(os.path.dirname(
                                                  os.path.abspath(path))), ws))

    def exists(self, path) -> bool:
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            return bool(c.execute("""select exists(select 1 from docs where workspace_id=%s and name=%s)
                                     or exists(select 1 from node_events where workspace_id=%s and log=%s)""",
                                  (ws, name, ws, name)).fetchone()[0])

    def remove(self, path):
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            c.execute("delete from docs where workspace_id=%s and name=%s", (ws, name))
            c.execute("select set_config('continuum.allow_reset', 'on', true)")
            c.execute("delete from node_events where workspace_id=%s and log=%s and not chained", (ws, name))

    def size(self, path) -> int:
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            row = c.execute("select coalesce(max(seq), 0) from node_events where workspace_id=%s and log=%s",
                            (ws, name)).fetchone()
        return int(row[0])

    # ---- logs
    def read_raw(self, path) -> list[str]:
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            rows = c.execute("select raw from node_events where workspace_id=%s and log=%s order by seq",
                             (ws, name)).fetchall()
        return [r[0] for r in rows]

    def read_lines(self, path) -> list[dict]:
        return [json.loads(r) for r in self.read_raw(path)]

    def _lock(self, c, ws, name):
        c.execute("select pg_advisory_xact_lock(hashtextextended(%s, 0))", (ws + "|" + name,))

    def _insert(self, c, ws, name, raw, ev, chained):
        from psycopg.types.json import Jsonb
        seq = c.execute("select coalesce(max(seq), 0) + 1 from node_events where workspace_id=%s and log=%s",
                        (ws, name)).fetchone()[0]
        actor = ev.get("actor") if isinstance(ev.get("actor"), dict) else ({"id": ev["actor"]} if ev.get("actor") else None)
        c.execute("""insert into node_events (workspace_id, log, seq, chained, event_id, node_type, node_id, op,
                                              actor, at, raw, event, prev_hash, hash)
                     values (%s,%s,%s,%s,%s,%s,%s,%s,%s, coalesce(%s::timestamptz, now()), %s,%s,%s,%s)""",
                  (ws, name, seq, chained, ev.get("event_id"), ev.get("entity_type"), ev.get("entity_id"),
                   ev.get("op"), Jsonb(actor) if actor else None, ev.get("ts"), raw, Jsonb(ev),
                   ev.get("prev_hash"), ev.get("hash")))
        return seq

    def append_line(self, path, obj):
        ws, name = workspace_of(path)
        with self.tx(ws) as c:
            self._ensure_ws(c, ws)
            self._lock(c, ws, name)
            self._insert(c, ws, name, json.dumps(obj), obj, False)

    def append_chained(self, path, event, heads_path, expect=None, seed_path=None):
        from psycopg.types.json import Jsonb
        ws, name = workspace_of(path)
        _hws, heads_name = workspace_of(heads_path)
        with self.tx(ws) as c:
            self._ensure_ws(c, ws)
            self._lock(c, ws, name)
            if expect is not None:
                row = c.execute("select version, status from nodes where workspace_id=%s and node_type=%s and id=%s",
                                (ws, expect[0], expect[1])).fetchone()
                _check_expect(tuple(row) if row else None, expect)
            last = c.execute("""select hash from node_events where workspace_id=%s and log=%s
                                order by seq desc limit 1""", (ws, name)).fetchone()
            event["prev_hash"] = (last[0] if last and last[0] else GENESIS_HASH)
            event["hash"] = hash_event(event)
            raw = json.dumps(event)
            self._insert(c, ws, name, raw, event, True)
            cnt = c.execute("select count(*) from node_events where workspace_id=%s and log=%s and chained",
                            (ws, name)).fetchone()[0]
            c.execute("""insert into docs (workspace_id, name, body, updated_at)
                         values (%s, %s, jsonb_build_object(%s::text, jsonb_build_object('head', %s::text, 'count', %s::int)), now())
                         on conflict (workspace_id, name) do update
                         set body = docs.body || excluded.body, updated_at = now()""",
                      (ws, heads_name, name, event["hash"], cnt))
            if name == EDITS_NAME:
                self._project(c, ws, event)
        return event

    def reset_log(self, path, heads_path):
        ws, name = workspace_of(path)
        _hws, heads_name = workspace_of(heads_path)
        with self.tx(ws) as c:
            self._lock(c, ws, name)
            c.execute("select set_config('continuum.allow_reset', 'on', true)")
            c.execute("delete from node_events where workspace_id=%s and log=%s", (ws, name))
            c.execute("update docs set body = body - %s where workspace_id=%s and name=%s", (name, ws, heads_name))
            if name == EDITS_NAME:
                self._reproject(c, ws)

    # ---- projection (nodes + edges): seed baseline, then every edit payload
    @staticmethod
    def _refs(attrs: dict):
        for k, v in attrs.items():
            if k.endswith("_refs") and isinstance(v, list):
                for t in v:
                    if isinstance(t, str) and t:
                        yield t, k
            elif k.endswith("_ref") and isinstance(v, str) and v:
                yield v, k

    def _upsert_node(self, c, ws, etype, attrs, source):
        from psycopg.types.json import Jsonb
        nid = attrs["id"]
        c.execute("""insert into nodes (workspace_id, node_type, id, name, status, version, attrs, source, updated_at)
                     values (%s,%s,%s,%s,%s,%s,%s,%s, now())
                     on conflict (workspace_id, node_type, id) do update set name=excluded.name, status=excluded.status,
                       version=excluded.version, attrs=excluded.attrs, source=excluded.source, updated_at=now()""",
                  (ws, etype, nid, str(attrs.get("name") or attrs.get("title") or nid)[:500], attrs.get("status"),
                   attrs.get("version"), Jsonb(attrs), source))
        c.execute("delete from edges where workspace_id=%s and source_id=%s and source_type=%s", (ws, nid, etype))
        rows = [(ws, etype, nid, t, k) for t, k in self._refs(attrs)]
        if rows:
            c.cursor().executemany("""insert into edges (workspace_id, source_type, source_id, target_id, edge_type)
                                      values (%s,%s,%s,%s,%s) on conflict do nothing""", rows)

    def _project(self, c, ws, ev):
        payload, op = ev.get("payload"), ev.get("op")
        if isinstance(payload, dict) and payload.get("id") and ev.get("entity_type"):
            if op == "deprecate":
                payload = {**payload, "status": "deprecated"}
            self._upsert_node(c, ws, ev["entity_type"], payload, "edit")

    def _reproject(self, c, ws):
        c.execute("delete from edges where workspace_id=%s", (ws,))
        c.execute("delete from nodes where workspace_id=%s", (ws,))
        row = c.execute("select body from docs where workspace_id=%s and name='seed.json'", (ws,)).fetchone()
        for etype, items in ((row[0] if row else {}) or {}).items():
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict) and it.get("id"):
                        self._upsert_node(c, ws, etype, it, "seed")
        for (raw,) in c.execute("select raw from node_events where workspace_id=%s and log=%s order by seq",
                                (ws, EDITS_NAME)).fetchall():
            self._project(c, ws, json.loads(raw))

    def list_workspaces(self) -> list[dict]:
        """Registered models in the current models dir (slug = the model's folder name)."""
        with self.tx(None) as c:
            rows = c.execute("""select id, slug, name, description, source from workspaces
                                where registered and id <> 'default' order by slug""").fetchall()
        mdir = models_dir_hook()
        return [{"slug": r[1], "name": r[2], "description": r[3], "source": r[4]} for r in rows
                if r[1] and workspace_of(os.path.join(mdir, r[1], "model.json"))[0] == r[0]]


# =========================================================================== selection
_BACKEND = None
_LOCK = threading.Lock()


def get() -> FileBackend | PostgresBackend:
    global _BACKEND
    if _BACKEND is None:
        with _LOCK:
            if _BACKEND is None:
                url = os.environ.get("CONTINUUM_DATABASE_URL")
                _BACKEND = PostgresBackend(url) if url else FileBackend()
    return _BACKEND


def use(backend) -> None:
    """Swap the process-wide backend (tests, the migrate / copy tools)."""
    global _BACKEND
    _BACKEND = backend
