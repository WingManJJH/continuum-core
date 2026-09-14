"""
Ask the Agent (D18) — a natural-language question over the Continuum graph.

The graph analog of a text-to-SQL "ask the data" agent: you ask a plain-English
question, the agent writes a **read-only** graph query, runs it against the one
graph, and answers with a table, the assumptions it made, and the exact query it
ran (the "Show query" receipt).

Two honest layers, mirroring the advisor's RulesAdvisor / LLMAdvisor split:

  * QueryEngine  — a real, read-only executor over the graph. It only ever reads
    (graph.all / graph.get); it never appends an event or edits an entity. This
    is what actually runs today.
  * Planner      — turns a question into a query plan. The deterministic
    IntentPlanner (keyword intents over a curated question set) stands in and
    works with no model access. The LLMPlanner is the declared seam where a live
    model generalizes to arbitrary questions once auth is provisioned; until
    then it refuses, exactly like the signal connectors and the pilot agent.

    python3 app.py            # http://localhost:8791
    python3 test_agent.py
"""
from __future__ import annotations

import os
import re
import sys
from typing import Any, Callable

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "advisor"))
import continuum_core as cc  # noqa: E402
import llm  # shared model seam  # noqa: E402
from advisor import HIGH_STAKES  # reuse the one high-stakes list  # noqa: E402

ID_RE = re.compile(r"\b(?:gr|kpi|agent|role|obj)\.[A-Za-z0-9_.]+|\b[A-Z]{2}\.\d+\.\d+\.\d+\b")

# --- query-plan whitelist (the LLM planner may only emit one of these) ------ #
ALLOWED_TYPES = {"StrategicObjective", "KPI", "Process", "Task", "HumanRole",
                 "AgentBinding", "GuardrailPolicy", "RiskControl"}
ALLOWED_OPS = {"absent", "present", "eq", "ne", "lt", "gt", "in", "intersects", "predicate"}
PLAN_KEYS = {"from", "active_only", "follow", "where", "select", "order_by", "limit"}
LIMIT_CAP = 200


# --------------------------------------------------------------------------- #
#  Read-only query executor                                                   #
# --------------------------------------------------------------------------- #
class QueryEngine:
    """Executes a read-only query plan against the graph. Never mutates."""

    def __init__(self, graph: cc.Graph | None = None):
        self.g = graph or cc.Graph()

    # -- graph-aware predicates (need traversal, so they live here) --------- #
    def _traces_to_objective(self, proc: dict) -> bool:
        for kref in proc.get("kpi_refs") or []:
            k = self.g.get("KPI", kref)
            if k and (k.get("objective_refs")):
                return True
        return False

    def _kpi_breaching(self, k: dict) -> bool:
        lv, tv = k.get("live_value"), k.get("target")
        if lv is None or tv is None:
            return False
        return (k.get("direction") == "lower_is_better" and lv > tv) or \
               (k.get("direction") == "higher_is_better" and lv < tv)

    def _agent_task(self, t: dict) -> bool:
        if any(str(p).startswith("agent.") for p in (t.get("performed_by") or [])):
            return True
        return any(b.get("task_ref") == t["id"] and b.get("status") == "active"
                   for b in self.g.all("AgentBinding"))

    def _effective_guardrail_absent(self, t: dict) -> bool:
        gr, _ = self.g.effective_guardrail(t["id"])
        return gr is None

    def _task_specific_guardrail_absent(self, t: dict) -> bool:
        return not t.get("guardrail_ref")

    def _high_stakes_allowed(self, gr: dict) -> list[str]:
        return sorted(set(gr.get("allowed_actions") or []) & HIGH_STAKES)

    def _unreviewed(self, gr: dict) -> bool:
        rev = gr.get("review")
        return not rev or not rev.get("reviewed_by")

    PREDS: dict[str, str] = {
        "traces_to_objective": "_traces_to_objective",
        "kpi_breaching": "_kpi_breaching",
        "agent_task": "_agent_task",
        "effective_guardrail_absent": "_effective_guardrail_absent",
        "task_specific_guardrail_absent": "_task_specific_guardrail_absent",
        "unreviewed": "_unreviewed",
    }

    # -- value access, including followed refs (dotted paths) --------------- #
    def _follow(self, row: dict, plan: dict) -> dict:
        joined = dict(row)
        for f in plan.get("follow", []):
            ref = row.get(f["via"])
            joined[f["as"]] = self.g.get(f["type"], ref) if ref else None
        return joined

    @staticmethod
    def _val(row: dict, path: str) -> Any:
        cur: Any = row
        for part in path.split("."):
            if cur is None:
                return None
            cur = cur.get(part) if isinstance(cur, dict) else None
        return cur

    def _test(self, row: dict, cond: dict) -> bool:
        op = cond["op"]
        if op == "predicate":
            fn = getattr(self, self.PREDS[cond["name"]])
            res = fn(row)
            out = bool(res)
            return (not out) if cond.get("negate") else out
        v = self._val(row, cond["path"])
        if op == "absent":
            return v is None or v == "" or v == [] or v == {}
        if op == "present":
            return not (v is None or v == "" or v == [] or v == {})
        if op == "eq":
            return v == cond["value"]
        if op == "ne":
            return v != cond["value"]
        if op == "lt":
            return v is not None and v < cond["value"]
        if op == "gt":
            return v is not None and v > cond["value"]
        if op == "in":
            return v in cond["value"]
        if op == "intersects":
            return bool(set(v or []) & set(cond["value"]))
        raise ValueError(f"unknown op {op}")

    def run(self, plan: dict) -> list[dict]:
        rows = self.g.all(plan["from"])
        if plan.get("active_only", True):
            rows = [r for r in rows if r.get("status") == "active"]
        rows = [self._follow(r, plan) for r in rows]
        for cond in plan.get("where", []):
            rows = [r for r in rows if self._test(r, cond)]
        ob = plan.get("order_by")
        if ob:
            rows.sort(key=lambda r: (self._val(r, ob["path"]) is None, self._val(r, ob["path"])),
                      reverse=(ob.get("dir") == "desc"))
        if plan.get("limit"):
            rows = rows[:plan["limit"]]
        return rows

    def count(self, plan: dict) -> int:
        return len(self.run(plan))

    def field_names(self, etype: str) -> set[str]:
        names: set[str] = set()
        for e in self.g.all(etype):
            names.update(e.keys())
        return names

    # single-value ref fields the LLM may FOLLOW, mapped to the type they point at
    FOLLOWABLE = {
        "guardrail_ref": "GuardrailPolicy", "process_ref": "Process",
        "task_ref": "Task", "owner_role": "HumanRole",
    }

    def schema_doc(self) -> str:
        """Human/model-readable description of the read-only query DSL + graph schema."""
        lines = ["READ-ONLY graph query plan (JSON). The plan can only READ; there is no write.",
                 "Shape:",
                 '  {"from": <EntityType>, "active_only": true,',
                 '   "follow": [{"as":"gr","type":"GuardrailPolicy","via":"guardrail_ref"}],',
                 '   "where": [ {"op":"absent","path":"guardrail_ref"},',
                 '              {"op":"predicate","name":"traces_to_objective","negate":true} ],',
                 '   "select": ["id","name"], "order_by":{"path":"maturity_score","dir":"asc"},',
                 '   "limit": 20 }',
                 "",
                 f"Entity types: {', '.join(sorted(ALLOWED_TYPES))}.",
                 f"Ops: {', '.join(sorted(ALLOWED_OPS))} "
                 "(absent/present take a path; eq/ne/lt/gt/in take path+value; "
                 "intersects takes a list path + value list; predicate takes name[+negate]).",
                 f"Predicates: {', '.join(sorted(self.PREDS))}.",
                 f"Followable ref fields: {', '.join(sorted(self.FOLLOWABLE))}.",
                 "", "Fields per type:"]
        for et in sorted(ALLOWED_TYPES):
            lines.append(f"  {et}: {', '.join(sorted(self.field_names(et)))}")
        lines.append("")
        lines.append("Return ONLY the JSON plan, no prose. Use select to name the columns to show.")
        return "\n".join(lines)


class PlanError(ValueError):
    """A query plan failed validation (unknown type/op/field, or oversized)."""


def validate_plan(plan: dict, engine: "QueryEngine") -> dict:
    """Whitelist a plan before it runs. Guarantees the plan is a bounded read."""
    if not isinstance(plan, dict):
        raise PlanError("plan is not an object")
    extra = set(plan) - PLAN_KEYS
    if extra:
        raise PlanError(f"unknown plan keys: {sorted(extra)}")
    et = plan.get("from")
    if et not in ALLOWED_TYPES:
        raise PlanError(f"'from' must be one of {sorted(ALLOWED_TYPES)}")
    fields = engine.field_names(et)
    aliases = set()
    for f in plan.get("follow", []) or []:
        if not isinstance(f, dict) or f.get("type") not in ALLOWED_TYPES:
            raise PlanError("bad follow.type")
        if f.get("via") not in engine.FOLLOWABLE:
            raise PlanError(f"follow.via must be one of {sorted(engine.FOLLOWABLE)}")
        aliases.add(f.get("as"))
    for c in plan.get("where", []) or []:
        if not isinstance(c, dict) or c.get("op") not in ALLOWED_OPS:
            raise PlanError(f"bad where op: {c.get('op') if isinstance(c, dict) else c}")
        if c["op"] == "predicate":
            if c.get("name") not in engine.PREDS:
                raise PlanError(f"unknown predicate: {c.get('name')}")
        else:
            head = str(c.get("path", "")).split(".")[0]
            if head not in fields and head not in aliases:
                raise PlanError(f"unknown field in where: {c.get('path')}")
    for s in plan.get("select", []) or []:
        head = str(s).split(".")[0]
        if head not in fields and head not in aliases:
            raise PlanError(f"unknown field in select: {s}")
    ob = plan.get("order_by")
    if ob and str(ob.get("path", "")).split(".")[0] not in (fields | aliases):
        raise PlanError(f"unknown field in order_by: {ob.get('path')}")
    lim = plan.get("limit")
    if lim is not None and (not isinstance(lim, int) or lim <= 0):
        raise PlanError("limit must be a positive integer")
    plan["limit"] = min(lim, LIMIT_CAP) if isinstance(lim, int) else LIMIT_CAP
    if not plan.get("select"):
        plan["select"] = ["id"] + (["name"] if "name" in fields else [])
    plan.setdefault("active_only", True)
    return plan


# --------------------------------------------------------------------------- #
#  Rendering the query as a readable, read-only receipt (the "Show query")    #
# --------------------------------------------------------------------------- #
def render_cql(plan: dict) -> str:
    lines = [f"FROM {plan['from']}"]
    for f in plan.get("follow", []):
        lines.append(f"FOLLOW {f['via']} -> {f['type']} AS {f['as']}")
    if plan.get("active_only", True):
        lines.append("WHERE status = 'active'")
        joiner = "  AND "
    else:
        joiner = "WHERE "
    conds = []
    for c in plan.get("where", []):
        if c["op"] == "predicate":
            name = c["name"] + "()"
            conds.append(("NOT " + name) if c.get("negate") else name)
        elif c["op"] in ("absent", "present"):
            conds.append(f"{c['path']} IS {'ABSENT' if c['op']=='absent' else 'PRESENT'}")
        elif c["op"] == "intersects":
            conds.append(f"{c['path']} INTERSECTS {c['value']}")
        else:
            conds.append(f"{c['path']} {c['op'].upper()} {c['value']!r}")
    for c in conds:
        lines.append(joiner + c)
        joiner = "  AND "
    if plan.get("select"):
        lines.append("SELECT " + ", ".join(plan["select"]))
    if plan.get("order_by"):
        lines.append(f"ORDER BY {plan['order_by']['path']} {plan['order_by'].get('dir','asc').upper()}")
    if plan.get("limit"):
        lines.append(f"LIMIT {plan['limit']}")
    return "\n".join(lines)


def _project(rows: list[dict], cols: list[str]) -> list[dict]:
    out = []
    for r in rows:
        o = {}
        for c in cols:
            v = QueryEngine._val(r, c)
            if isinstance(v, list):
                o[c] = ", ".join(map(str, v))
            elif isinstance(v, dict):
                o[c] = " ".join(f"{k}:{vv}" for k, vv in v.items())
            else:
                o[c] = "" if v is None else v
        out.append(o)
    return out


# --------------------------------------------------------------------------- #
#  Intents — a question maps to a plan + how to phrase the answer             #
# --------------------------------------------------------------------------- #
class Intent:
    def __init__(self, iid: str, utterance: str, combos: list[list[str]],
                 plan: dict, columns: list[str],
                 summarize: Callable[[list[dict], int, "QueryEngine"], str],
                 assumptions: list[str] | None = None):
        self.id = iid
        self.utterance = utterance
        self.combos = combos          # each: all tokens must appear -> full match
        self.plan = plan
        self.columns = columns
        self.summarize = summarize
        self.assumptions = assumptions or []

    def match_score(self, q: str) -> int:
        best = 0
        for combo in self.combos:
            if all(tok in q for tok in combo):
                best = max(best, sum(len(tok) for tok in combo))
        return best


def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


INTENTS: list[Intent] = [
    Intent(
        "ungoverned_processes",
        "Which processes have no guardrail?",
        [["process", "no guardrail"], ["process", "without guardrail"],
         ["ungoverned", "process"], ["process", "not governed"]],
        {"from": "Process", "where": [{"op": "absent", "path": "guardrail_ref"}],
         "select": ["id", "name", "owner_role"]},
        ["id", "name", "owner_role"],
        lambda rows, n, e: (
            "Every active process has a guardrail attached — none are ungoverned."
            if n == 0 else
            f"{_plural(n,'process has','processes have')} no guardrail attached: "
            + ", ".join(r["id"] for r in rows) + "."),
        ["'Governed' means a guardrail is directly attached to the process record.",
         "A stamped default counts as attached even if it has not been reviewed yet."],
    ),
    Intent(
        "unreviewed_guardrails",
        "Which guardrails are unreviewed defaults?",
        [["guardrail", "unreviewed"], ["guardrail", "not reviewed"],
         ["guardrail", "not signed"], ["default", "guardrail", "review"]],
        {"from": "GuardrailPolicy", "where": [{"op": "predicate", "name": "unreviewed"}],
         "select": ["id", "attaches_to", "version"]},
        ["id", "attaches_to", "version"],
        lambda rows, n, e: (
            "All active guardrails carry a review sign-off."
            if n == 0 else
            f"{_plural(n,'guardrail has','guardrails have')} no reviewer on record "
            "(a stamped default awaiting QMS sign-off): "
            + ", ".join(r["id"] for r in rows) + "."),
        ["'Reviewed' means the guardrail's review block names a reviewer (ISO 9001 §12 coverage).",
         "New processes stamp a default guardrail that is unreviewed until signed off."],
    ),
    Intent(
        "dangling_processes",
        "Which processes do not trace to a strategic objective?",
        [["process", "trace", "objective"], ["process", "no", "objective"],
         ["dangling", "process"], ["process", "strategy"], ["orphan", "process"]],
        {"from": "Process",
         "where": [{"op": "predicate", "name": "traces_to_objective", "negate": True}],
         "select": ["id", "name", "kpi_refs"]},
        ["id", "name", "kpi_refs"],
        lambda rows, n, e: (
            "Every process traces up to a strategic objective through its KPIs."
            if n == 0 else
            f"{_plural(n,'process does','processes do')} not trace to any strategic "
            "objective (a broken golden thread): "
            + ", ".join(r["id"] for r in rows) + "."),
        ["Traceability path: Process -> its KPIs -> those KPIs' objective_refs.",
         "A process with no KPI, or KPIs that name no objective, is treated as dangling (§12)."],
    ),
    Intent(
        "agent_steps",
        "Which tasks have an agent bound?",
        [["agent", "task"], ["agent", "step"], ["agent", "bound"],
         ["where", "agent"], ["tasks", "agent"]],
        {"from": "Task", "where": [{"op": "predicate", "name": "agent_task"}],
         "follow": [{"as": "proc", "type": "Process", "via": "process_ref"}],
         "select": ["id", "name", "process_ref"], "order_by": {"path": "id"}},
        ["id", "name", "process_ref"],
        lambda rows, n, e: (
            "No task currently has an agent bound to it."
            if n == 0 else
            f"{_plural(n,'task has','tasks have')} an agent in the loop: "
            + ", ".join(r["id"] for r in rows) + "."),
        ["An 'agent step' = the task lists an agent performer or has an active AgentBinding.",
         "Both human-and-agent and agent-only steps are included."],
    ),
    Intent(
        "agent_no_task_guardrail",
        "Which agent steps rely on an inherited guardrail rather than a task-specific one?",
        [["agent", "guardrail", "task"], ["agent", "fail"], ["agent", "no guardrail"],
         ["agent", "unguarded"], ["agent", "inherited", "guardrail"]],
        {"from": "Task",
         "where": [{"op": "predicate", "name": "agent_task"},
                   {"op": "predicate", "name": "task_specific_guardrail_absent"}],
         "select": ["id", "name", "process_ref"], "order_by": {"path": "id"}},
        ["id", "name", "process_ref"],
        lambda rows, n, e: (
            "Every agent step has a guardrail attached directly to the task."
            if n == 0 else
            f"{_plural(n,'agent step','agent steps')} "
            + ("has" if n == 1 else "have")
            + " no task-specific guardrail and rely on the process-level guardrail inherited: "
            + ", ".join(r["id"] for r in rows)
            + ". None are fail-open (all still inherit a guardrail), but a task-level "
            "guardrail is more precise for an agent."),
        ["Continuum resolves a task's effective guardrail as task-level, else the process's.",
         "This lists agent tasks with no *direct* guardrail; all here still inherit one."],
    ),
    Intent(
        "kpis_breaching",
        "Which KPIs are off target?",
        [["kpi", "off target"], ["kpi", "breach"], ["kpi", "missing target"],
         ["kpi", "behind"], ["kpi", "not meeting"], ["kpi", "red"]],
        {"from": "KPI", "where": [{"op": "predicate", "name": "kpi_breaching"}],
         "select": ["id", "name", "live_value", "target", "direction"]},
        ["id", "name", "live_value", "target", "direction"],
        lambda rows, n, e: (
            "Every KPI with a live value is at or better than target."
            if n == 0 else
            f"{_plural(n,'KPI is','KPIs are')} off target: "
            + ", ".join(f"{r['name']} ({r['live_value']} vs {r['target']})" for r in rows) + "."),
        ["Breach = live_value worse than target given the KPI's direction "
         "(lower_is_better -> live > target; higher_is_better -> live < target).",
         "KPIs with no live value are not evaluated."],
    ),
    Intent(
        "lowest_maturity",
        "Which processes have the lowest maturity?",
        [["lowest", "maturity"], ["least", "mature"], ["weakest", "process"],
         ["maturity", "process"], ["immature", "process"]],
        {"from": "Process", "select": ["id", "name", "maturity_score"],
         "order_by": {"path": "maturity_score", "dir": "asc"}, "limit": 5},
        ["id", "name", "maturity_score"],
        lambda rows, n, e: (
            "The five lowest-maturity processes: "
            + ", ".join(f"{r['id']} (maturity {r['maturity_score']})" for r in rows) + "."),
        ["Maturity is the 1-5 self-assessed process-design score on each process (ISO 9004).",
         "Ties are broken by id order; showing the bottom 5."],
    ),
    Intent(
        "high_stakes_guardrails",
        "Which guardrails allow a high-stakes action?",
        [["guardrail", "high-stakes"], ["guardrail", "high stakes"],
         ["guardrail", "dangerous"], ["guardrail", "risky action"],
         ["guardrail", "sensitive action"]],
        {"from": "GuardrailPolicy", "select": ["id", "allowed_actions"]},  # filtered in summarize
        ["id", "high_stakes_actions"],
        None,  # custom below
        ["High-stakes actions: " + ", ".join(sorted(HIGH_STAKES)) + " (§11: never unattended).",
         "A guardrail may still be safe if that action requires escalation; this flags it for review."],
    ),
    Intent(
        "apqc_domains",
        "Which APQC domains does the model cover?",
        [["apqc", "domain"], ["apqc", "cover"], ["domains", "cover"],
         ["how many", "domain"], ["apqc", "process"]],
        {"from": "Process", "select": ["id", "apqc_code", "name"], "order_by": {"path": "apqc_code"}},
        ["apqc_code", "id", "name"],
        lambda rows, n, e: (
            f"The model spans {len({r['apqc_code'][:2] for r in rows})} APQC domains across "
            f"{n} processes: "
            + ", ".join(sorted({r["apqc_code"][:2] for r in rows})) + "."),
        ["APQC domain is taken as the two-letter prefix of each process's APQC code.",
         "One seed process per domain in this prototype."],
    ),
]


# --------------------------------------------------------------------------- #
#  Planners                                                                    #
# --------------------------------------------------------------------------- #
SYSTEM_PROMPT = (
    "You translate a question about a governance graph into ONE read-only query plan. "
    "You never write, mutate, or invent data — you only select what to read. "
    "Reply with a single JSON object (the plan) and nothing else.")


class LLMPlanner:
    """The auth-gated seam: a live model that turns ANY question into a query.

    Wired behind an env var. When CONTINUUM_LLM_API_KEY (or ANTHROPIC_API_KEY) is
    set, it asks the model for a query *plan* — never code — and that plan is
    whitelisted by validate_plan before the read-only QueryEngine runs it, so even
    a hostile or hallucinated response can do nothing but a bounded read. When no
    key is set it refuses, exactly like the signal connectors, the pilot agent, and
    the advisor's LLMAdvisor; the deterministic IntentPlanner stands in.

    `transport` is an optional callable(question, schema_doc) -> raw model text,
    injected for tests so the full path runs with no key and no network.
    """

    def __init__(self, engine: "QueryEngine", transport=None):
        self.engine = engine
        self._transport = transport

    def available(self) -> bool:
        return llm.available(self._transport)

    @property
    def model(self) -> str:
        return llm.model()

    def plan(self, question: str) -> dict:
        if not self.available():
            raise RuntimeError(
                "LLMPlanner requires model access — set CONTINUUM_LLM_API_KEY (or "
                "ANTHROPIC_API_KEY) to enable it. The deterministic IntentPlanner is "
                "answering the curated question set instead.")
        raw = llm.call_model(SYSTEM_PROMPT, self.engine.schema_doc() + "\n\nQuestion: " + question,
                             transport=self._transport)
        parsed = llm.extract_json(raw)
        if not isinstance(parsed, dict):
            raise PlanError("model did not return a query-plan object")
        return validate_plan(parsed, self.engine)


class Agent:
    """Ask a question, get an answer + the read-only query that produced it."""

    def __init__(self, graph: cc.Graph | None = None, llm_transport=None):
        self.engine = QueryEngine(graph)
        self.g = self.engine.g
        self.llm = LLMPlanner(self.engine, transport=llm_transport)

    def examples(self) -> list[str]:
        return [i.utterance for i in INTENTS]

    def _llm_answer(self, question: str) -> dict | None:
        """Try the env-gated LLM planner. Returns a result, or None to fall back."""
        if not self.llm.available():
            return None
        try:
            plan = self.llm.plan(question)
            rows = self.engine.run(plan)
            cols = plan.get("select") or ["id"]
            proj = _project(rows, cols)
            answer = ("The LLM planner wrote a read-only query for that and it returned "
                      + (f"{_plural(len(proj),'row','rows')}:" if proj
                         else "no matching rows."))
            return {
                "matched": True, "intent": "llm_planner", "planner": "llm",
                "answer": answer, "columns": cols, "rows": proj, "n": len(proj),
                "cql": render_cql(plan), "assumptions": [
                    f"Query written by the LLM planner ({self.llm.model}) from your question.",
                    "The plan was whitelist-validated as a bounded, read-only query before running."],
                "note": "", "suggestions": [],
            }
        except Exception as e:  # noqa: BLE001 - surface as an honest note, then fall back
            return {"_llm_error": f"{type(e).__name__}: {e}"}

    # -- entity lookup (an id in the question) ------------------------------ #
    def _describe_entity(self, ident: str) -> dict | None:
        for et in ("Process", "GuardrailPolicy", "Task", "KPI", "AgentBinding",
                   "StrategicObjective", "HumanRole", "RiskControl"):
            ent = self.g.get(et, ident)
            if ent:
                fields = [k for k in ent if k not in ("status",)]
                rows = [{"field": k, "value": ", ".join(map(str, ent[k]))
                         if isinstance(ent[k], list) else str(ent[k])} for k in fields]
                return {
                    "matched": True, "intent": "entity_detail", "planner": "lookup",
                    "answer": f"{et} {ident}"
                              + (f" — {ent.get('name')}" if ent.get("name") else "")
                              + f" (status: {ent.get('status','?')}).",
                    "columns": ["field", "value"], "rows": rows, "n": len(rows),
                    "cql": f"GET {et} WHERE id = '{ident}'",
                    "assumptions": ["Direct entity lookup by id — the full stored record."],
                    "note": "", "suggestions": [],
                }
        return None

    def _high_stakes_result(self, intent: Intent) -> dict:
        rows = []
        for gr in self.engine.run(intent.plan):
            hs = self.engine._high_stakes_allowed(gr)
            if hs:
                rows.append({"id": gr["id"], "high_stakes_actions": ", ".join(hs)})
        n = len(rows)
        answer = ("No active guardrail allows a high-stakes action outright — clean against §11."
                  if n == 0 else
                  f"{_plural(n,'guardrail allows','guardrails allow')} a high-stakes action; "
                  "confirm each requires escalation: " + ", ".join(r["id"] for r in rows) + ".")
        return self._wrap(intent, ["id", "high_stakes_actions"], rows, answer)

    def _wrap(self, intent: Intent, columns, rows, answer) -> dict:
        return {
            "matched": True, "intent": intent.id, "planner": "intent", "answer": answer,
            "columns": columns, "rows": rows, "n": len(rows),
            "cql": render_cql(intent.plan), "assumptions": intent.assumptions,
            "note": "", "suggestions": [],
        }

    def ask(self, question: str) -> dict:
        q = (question or "").lower().strip()
        out = {"question": question}
        if not q:
            out.update({"matched": False, "planner": "none", "answer": "Ask a question about the model.",
                        "columns": [], "rows": [], "n": 0, "cql": "", "assumptions": [],
                        "note": "", "suggestions": self.examples()})
            return out

        # 1) a specific id in the question -> entity detail
        m = ID_RE.search(question or "")
        if m and any(w in q for w in ("about", "detail", "show", "what is", "tell me", "describe")):
            ent = self._describe_entity(m.group(0))
            if ent:
                out.update(ent)
                return out

        # 2) intent match (deterministic planner standing in for the LLM planner)
        ranked = sorted(((i.match_score(q), i) for i in INTENTS), key=lambda x: x[0], reverse=True)
        top_score, top = ranked[0]
        if top_score > 0:
            if top.id == "high_stakes_guardrails":
                out.update(self._high_stakes_result(top))
                return out
            rows = self.engine.run(top.plan)
            proj = _project(rows, top.columns)
            out.update(self._wrap(top, top.columns, proj, top.summarize(proj, len(proj), self.engine)))
            return out

        # 3) unmatched -> if the LLM planner is enabled, let it write the query
        llm = self._llm_answer(q if q else question)
        llm_err = None
        if llm and "_llm_error" not in llm:
            out.update(llm)
            return out
        if llm:
            llm_err = llm["_llm_error"]

        # 4) unmatched + no (working) LLM planner -> honest seam note + suggestions
        if llm_err:
            answer = ("The LLM planner is enabled but could not turn that into a valid read-only "
                      "query. The deterministic planner covers the questions below.")
            note = f"LLM planner error: {llm_err}"
        else:
            answer = ("I can't turn that into a read-only query yet. The deterministic planner "
                      "covers the questions below; open-ended phrasing needs the LLM planner, "
                      "which is declared but auth-gated (no model access yet).")
            note = ("LLMPlanner is the seam for arbitrary questions — set CONTINUUM_LLM_API_KEY "
                    "(or ANTHROPIC_API_KEY) to enable it.")
        out.update({
            "matched": False, "planner": "none", "answer": answer,
            "columns": [], "rows": [], "n": 0, "cql": "", "assumptions": [],
            "note": note, "suggestions": self.examples(),
        })
        return out


if __name__ == "__main__":
    a = Agent()
    for utt in a.examples():
        r = a.ask(utt)
        print(f"\nQ: {utt}\nA: {r['answer']}\n--- query ---\n{r['cql']}")
