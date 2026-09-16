"""
Build a process from a list of instructions (natural language -> governed process).

Two engines, one output. Both turn instructions into the same parsed structure the
importer applies (`bpmn.import_bpmn.apply_parsed`), so a built process is created
through the exact same versioned, hash-chained write path as everything else and
is fully editable in the canvas afterwards.

  - a deterministic reader (always available, no key): reads a numbered / bulleted /
    one-per-line list, extracts each step, deduces a performing role, flags
    automated ("the system…", "automatically…") steps as agent steps, and models
    decision lines ("If…", "…?", "decide whether…") as gateways.
  - an LLM reader (richer deduction) behind the existing CONTINUUM_LLM_API_KEY seam
    (mcp_server/llm.py): the model returns a **validated JSON plan** (data, not code)
    that is whitelisted before anything is created — same safety pattern as the Ask
    planner. With no key it simply isn't used; the deterministic reader stands in.

Everything it assumes is surfaced in an **assumptions** list — nothing is hidden.
It deduces and attaches what it can honestly infer (steps, order, performers +
their roles, decisions, agent steps, and the default guardrail); it *suggests*
KPIs / risks / an owner rather than fabricating them. Preview first — plan_build
writes nothing; apply_build (through apply_parsed) is the only writer.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "bpmn"))
import llm  # noqa: E402
import import_bpmn as _imp  # noqa: E402  — shared apply/plan

MAX_STEPS = 60
_AGENT_RE = re.compile(r"\b(automatical|automated|auto-|the system|system (?:will|then|automatically)|"
                       r"\bAI\b|\bbot\b|\bRPA\b|a script|scripted)\b", re.I)
_DECISION_RE = re.compile(r"^(if|whether)\b|\?\s*$|"
                          r"\b(decide|determine|check|choose) (whether|if)\b|\bdecision\b|"
                          r"\beither\b.*\bor\b", re.I)
_LIST_MARK = re.compile(r"^\s*(?:\d+[.)]|[-*•·])\s+")


def _slug(name: str) -> str | None:
    s = re.sub(r"[^a-z0-9]+", "_", (name or "").strip().lower()).strip("_")
    return ("role." + s) if s else None


def _role_from_line(line: str):
    """Return (role_id, role_name, remaining_text) deduced from a step line, or
    (None, None, line)."""
    m = re.match(r"^([A-Z][A-Za-z][A-Za-z /&]{1,30}?):\s*(.+)$", line)   # "AP Clerk: verify the invoice"
    if m and len(m.group(1).split()) <= 4:
        return _slug(m.group(1)), m.group(1).strip(), m.group(2).strip()
    m = re.search(r"\bby (?:the )?([A-Za-z][\w]*(?: [A-Za-z][\w]*){0,3})", line)  # "... by the AP clerk"
    if m:
        nm = m.group(1).strip()
        if nm.lower() not in ("email", "hand", "phone", "default", "now", "then"):
            return _slug(nm), nm.title(), line
    m = re.match(r"^(?:The )?([A-Z][a-z]+(?: [A-Z][a-z]+)+)\s+([a-z]\w+)", line)  # "Finance Manager approves ..."
    if m:
        return _slug(m.group(1)), m.group(1).strip(), line
    return None, None, line


def _clean_name(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(".")
    if text and text[0].islower():
        text = text[0].upper() + text[1:]
    return text[:120] or "Step"


def _items_from_text(text: str):
    """Deterministic reader -> (name, items, assumptions, warnings)."""
    text = (text or "").replace("\r\n", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    assumptions: list[str] = []
    warnings: list[str] = []

    name = "Process from instructions"
    kept = []
    for ln in lines:
        if not ln:
            continue
        m = re.match(r"^(process|title|name)\s*[:\-]\s*(.+)$", ln, re.I)
        if m and not kept:
            name = _clean_name(m.group(2))
            continue
        kept.append(ln)
    if name == "Process from instructions":
        assumptions.append("No process name was given — used \"Process from instructions\".")

    # one blob with no list structure -> split into sentences
    if len(kept) <= 1 and kept:
        kept = [s.strip() for s in re.split(r"(?<=[.!?])\s+", kept[0]) if s.strip()]

    items = []
    for ln in kept[:MAX_STEPS]:
        ln = _LIST_MARK.sub("", ln).strip()
        if not ln:
            continue
        role_id, role_name, rest = _role_from_line(ln)
        agent = bool(_AGENT_RE.search(ln))
        kind = "gateway" if _DECISION_RE.search(rest) else "task"
        items.append({"name": _clean_name(rest), "kind": kind,
                      "role": role_id, "role_name": role_name, "agent": agent})
    if not items:
        raise ValueError("no steps found — give one instruction per line, or a numbered list")
    return name, items, assumptions, warnings


def _assemble(name: str, items: list, assumptions: list, warnings: list, source: str) -> dict:
    tasks, gateways, flows, roles = [], [], [], {}
    chain = ["__S__"]
    no_perf, agents, decisions = [], [], []
    for i, it in enumerate(items):
        nid = "n%d" % i
        chain.append(nid)
        if it.get("role") and it.get("role_name"):
            roles[it["role"]] = it["role_name"]
        if it["kind"] == "gateway":
            gateways.append({"bpmn_id": nid, "type": "exclusive", "name": it["name"][:80], "x": i})
            decisions.append(it["name"])
        else:
            tasks.append({"bpmn_id": nid, "name": it["name"], "agent": it["agent"],
                          "role": it.get("role"), "x": i})
            if not it.get("role"):
                no_perf.append("step %d" % (len([t for t in tasks])))
            if it["agent"]:
                agents.append(it["name"])
    chain.append("__E__")
    for j in range(len(chain) - 1):
        flows.append({"bpmn_id": "f%d" % j, "source": chain[j], "target": chain[j + 1], "condition": None})

    if no_perf:
        assumptions.append("No performer was stated for %d step(s) — left to the process owner; "
                           "assign roles in the canvas or via Manage roles." % len(no_perf))
    if agents:
        assumptions.append("Modeled as automated (agent) step(s): " + ", ".join(agents[:6])
                           + ("…" if len(agents) > 6 else "") + ". They inherit the process guardrail.")
    if decisions:
        assumptions.append("Modeled %d decision(s) as gateways: " % len(decisions)
                           + ", ".join(decisions[:6]) + ". Add each branch's condition in the canvas.")
    if roles:
        assumptions.append("Deduced role(s): " + ", ".join(sorted(set(roles.values())))
                           + " (created if new).")
    assumptions.append("Applied the default (unreviewed) guardrail to the new process — review it before agents rely on it.")
    assumptions.append("No KPIs or risks were inferred (they aren't guessed) — add them in the canvas or ask the Advisor.")

    return {"name": name, "tasks": tasks, "gateways": gateways, "events": [], "flows": flows,
            "roles": [{"id": rid, "name": nm} for rid, nm in roles.items()],
            "start_ids": ["__S__"], "end_ids": ["__E__"],  # lists — this plan is JSON-returned to the client
            "assumptions": assumptions, "warnings": warnings, "source": source}


# --- LLM reader ------------------------------------------------------------
_SYS = (
    "You convert a list of business-process instructions into a strict JSON plan. "
    "Return ONLY JSON, no prose, shaped exactly:\n"
    '{"name": "<short process name>", "steps": [{"name": "<imperative step, <=100 chars>", '
    '"performer": "<role or team, or null>", "automated": <true if a system/agent does it, else false>, '
    '"decision": <true if this is a yes/no decision point, else false>}]}\n'
    "Order the steps as they happen. Infer a sensible performer per step when the text implies one; "
    "use null when unknown. Keep it faithful to the instructions; do not invent extra steps."
)


def _items_from_llm(text: str, transport=None):
    """LLM reader -> (name, items) validated, or None if unavailable / unusable."""
    if not llm.available(transport):
        return None
    try:
        raw = llm.call_model(_SYS, (text or "").strip()[:6000], transport=transport, max_tokens=1500)
        obj = llm.extract_json(raw)
    except Exception:  # noqa: BLE001 — any model/parse error -> fall back
        return None
    if not isinstance(obj, dict) or not isinstance(obj.get("steps"), list):
        return None
    name = _clean_name(str(obj.get("name") or "Process from instructions"))
    items = []
    for s in obj["steps"][:MAX_STEPS]:
        if not isinstance(s, dict) or not str(s.get("name", "")).strip():
            continue
        perf = s.get("performer")
        rid = _slug(str(perf)) if perf and str(perf).strip().lower() not in ("null", "none", "n/a") else None
        items.append({"name": _clean_name(str(s["name"])), "kind": "gateway" if s.get("decision") else "task",
                      "role": rid, "role_name": (str(perf).strip().title() if rid else None),
                      "agent": bool(s.get("automated"))})
    return (name, items) if items else None


# --- public API ------------------------------------------------------------
def build_parsed(text: str, use_llm: bool = False, transport=None) -> dict:
    """Return the parsed plan (deterministic, or LLM when asked + available)."""
    if use_llm:
        got = _items_from_llm(text, transport)
        if got:
            name, items = got
            return _assemble(name, items, ["Deduced by the AI planner from your instructions."], [], "llm")
    name, items, assumptions, warnings = _items_from_text(text)
    return _assemble(name, items, assumptions, warnings, "rules")


def _preview(parsed: dict) -> list[dict]:
    order = {}
    for t in parsed["tasks"]:
        order[t["bpmn_id"]] = {"name": t["name"], "kind": "step", "role": t.get("role"), "agent": t["agent"]}
    for gw in parsed["gateways"]:
        order[gw["bpmn_id"]] = {"name": gw["name"], "kind": "decision", "role": None, "agent": False}
    out = []
    for f in parsed["flows"]:
        if f["source"] in order and (not out or out[-1]["_id"] != f["source"]):
            out.append(dict(order[f["source"]], _id=f["source"]))
        if f["target"] in order:
            out.append(dict(order[f["target"]], _id=f["target"]))
    seen, seq = set(), []
    for o in out:
        if o["_id"] in seen:
            continue
        seen.add(o["_id"]); o.pop("_id")
        seq.append(o)
    return seq


def plan_build(text: str, use_llm: bool = False, transport=None) -> dict:
    """A dry-run: the deduced plan + assumptions + a readable step preview. Writes
    nothing. The returned `parsed` is what apply_build will create verbatim."""
    parsed = build_parsed(text, use_llm=use_llm, transport=transport)
    summary = _imp.plan_from_parsed(parsed)
    summary["source"] = parsed.get("source", "rules")
    summary["assumptions"] = parsed.get("assumptions", [])
    summary["preview"] = _preview(parsed)
    return {"parsed": parsed, "plan": summary}


def apply_build(parsed: dict, code=None, owner=None, actor=_imp.DEFAULT_OWNER,
                reason: str = "built from instructions", store=None) -> dict:
    """Create the process from a parsed plan through the audited write path."""
    return _imp.apply_parsed(parsed, code=code, owner=owner, actor=actor, reason=reason, store=store)


if __name__ == "__main__":
    import json
    sample = ("Process: Vendor onboarding\n"
              "1. Procurement Lead receives the vendor request\n"
              "2. The system automatically checks the vendor against the sanctions list\n"
              "3. If the vendor is high risk, escalate to the CISO\n"
              "4. Finance Manager approves the vendor\n"
              "5. Buyer creates the purchase order")
    print(json.dumps(plan_build(sample)["plan"], indent=2))
