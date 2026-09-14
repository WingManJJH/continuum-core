"""
Standards advisor — analyze any subject against best practices & standards.

Given a process, guardrail, task, arbitrary content/data, or the whole model, this
returns a scorecard + findings, each citing the standard it comes from: ISO 9001
(§4.4 process approach, §7.5 documented information, §7.5.3 retention), ISO 9004
(maturity / PDCA), APQC PCF, and the Core Model's own doctrine (§04 enforcement,
§11 guardrail design, §12 traceability & coverage) — plus least-privilege.

The rules here are deterministic and need no model access, so the advisor works
today. A deeper natural-language review (nuance a rule set can't reach) is the
LLMAdvisor seam below — auth-gated and declared, not faked (like the signal
connectors). The RulesAdvisor stands in and is what the agent window uses now.
"""
from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, os.path.join(HERE, "..", "dashboard"))
import continuum_core as cc  # noqa: E402
import traceability as trace  # noqa: E402
from rollup import Rollup  # noqa: E402

STD = {
    "iso9001_44": "ISO 9001 §4.4 — process approach",
    "iso9001_75": "ISO 9001 §7.5 — documented information",
    "iso9001_753": "ISO 9001 §7.5.3 — retention & disposition",
    "iso9004": "ISO 9004 — maturity / PDCA",
    "apqc": "APQC PCF — classification & join key",
    "cm_04": "Continuum §04 — enforcement",
    "cm_11": "Continuum §11 — guardrail doctrine",
    "cm_12": "Continuum §12 — traceability & coverage",
    "least_privilege": "Least privilege",
}
# actions a guardrail should not let an agent take unattended (§11)
HIGH_STAKES = {"approve", "reject_final", "disburse_funds", "modify_permissions",
               "delete_record", "send_external", "close_case", "approve_credit_limit",
               "grant_admin_access", "modify_vendor"}


def _c(std, ok, severity, title, detail, rec=""):
    return {"standard": STD[std], "std_id": std, "ok": ok,
            "severity": "pass" if ok else severity,
            "title": title, "detail": detail, "recommendation": rec}


def _score(checks):
    n = len(checks) or 1
    return round(sum(1 for c in checks if c["ok"]) / n * 100)


def _wrap(subject, kind, checks, note=""):
    fails = [c for c in checks if not c["ok"]]
    fails.sort(key=lambda c: {"high": 0, "medium": 1, "low": 2, "info": 3}.get(c["severity"], 4))
    return {"subject": subject, "kind": kind, "score": _score(checks),
            "n_checks": len(checks), "n_findings": len(fails),
            "checks": checks, "findings": fails, "note": note}


# --------------------------------------------------------------------------
class RulesAdvisor:
    def __init__(self, graph: cc.Graph | None = None):
        self.g = graph or cc.Graph()
        self._kpi_to_obj = {}
        for o in self.g.all("StrategicObjective"):
            for k in o.get("kpi_refs", []):
                self._kpi_to_obj.setdefault(k, []).append(o["id"])

    # ---- process (ISO 9001 §4.4 + Core Model) ----------------------------
    def process(self, pid: str) -> dict:
        p = self.g.get("Process", pid)
        if not p:
            return {"error": f"unknown process {pid}"}
        reaches_obj = any(self._kpi_to_obj.get(k) for k in p.get("kpi_refs", []))
        checks = [
            _c("iso9001_44", bool(p.get("owner_role")), "high", "Single accountable owner",
               f"owner_role = {p.get('owner_role') or 'MISSING'}",
               "Name one accountable role (not a team) — §4.4 requires it."),
            _c("iso9001_44", bool(p.get("inputs")) and bool(p.get("outputs")), "medium",
               "Typed inputs & outputs", f"{len(p.get('inputs', []))} in / {len(p.get('outputs', []))} out",
               "Declare typed inputs/outputs so conformance checking is possible (§06)."),
            _c("iso9001_44", bool(p.get("kpi_refs")), "medium", "Monitoring via KPIs",
               f"{len(p.get('kpi_refs', []))} KPI(s)", "Attach at least one KPI so the process is monitored (§4.4)."),
            _c("cm_12", reaches_obj, "medium", "Traces to a strategic objective",
               "reaches an objective" if reaches_obj else "no KPI reaches an objective",
               "Link a KPI to an objective, or this process is a data-quality defect (§12)."),
            _c("cm_04", bool(p.get("guardrail_ref")), "high", "Governed by a guardrail",
               f"guardrail_ref = {p.get('guardrail_ref') or 'MISSING'}",
               "Attach a guardrail so agent actions here are enforced (§04)."),
            _c("iso9004", p.get("maturity_score") is not None, "info", "Maturity self-assessment",
               f"score = {p.get('maturity_score')}", "Set an ISO 9004 1–5 maturity score and track it."),
            _c("iso9001_44", bool(p.get("risk_refs")), "low", "Risk & control linked",
               f"{len(p.get('risk_refs', []))} risk(s)", "Link a Risk & Control register entry."),
            _c("apqc", bool(re.match(r"^[A-Z]{2}\.[0-9.]+$", p.get("apqc_code", ""))), "info",
               "APQC-classified", f"apqc_code = {p.get('apqc_code')}", "Keep the APQC code as the join key."),
        ]
        return _wrap(f"Process {pid} — {p['name']}", "process", checks)

    # ---- guardrail (§11 doctrine + §04) ----------------------------------
    def guardrail(self, gid: str) -> dict:
        gr = self.g.get("GuardrailPolicy", gid)
        if not gr:
            return {"error": f"unknown guardrail {gid}"}
        allowed = set(gr.get("allowed_actions", []))
        risky = sorted(allowed & HIGH_STAKES)
        esc = gr.get("escalate_if")
        esc_ok = True
        if esc:
            try:
                cc._safe_eval(esc, {})
            except Exception:  # noqa: BLE001
                esc_ok = False
        reviewed = bool(gr.get("review", {}).get("reviewed_by"))
        checks = [
            _c("cm_11", bool(allowed), "high", "Has an allow-list",
               f"{len(allowed)} allowed action(s)", "An empty allow-list makes the agent useless — grant a scoped set."),
            _c("cm_11", not risky, "high", "No high-stakes action allowed unattended",
               ("allows: " + ", ".join(risky)) if risky else "no irreversible/outward actions allowed",
               "Move " + (", ".join(risky) or "such actions") + " to forbidden or behind escalation (§11)."),
            _c("cm_11", bool(gr.get("forbidden_actions")), "low", "Explicit deny-list",
               f"{len(gr.get('forbidden_actions', []))} forbidden", "List deliberate exclusions so an audit sees them (§11)."),
            _c("cm_11", esc_ok, "medium", "Escalation condition valid",
               (f"escalate_if = {esc}" if esc else "no escalate_if — confirm the step needs none"),
               "" if esc else "If any case should reach a human, add an escalate_if condition (§11 escalation calibration)."),
            _c("least_privilege", bool(gr.get("data_scope")), "medium", "Least-privilege data scope",
               f"scope = {gr.get('data_scope') or 'EMPTY (nothing granted / or too broad if inherited)'}",
               "Scope to the exact fields the step needs — never the whole record (§04)."),
            _c("cm_04", str(gr.get("escalation_path", "")).startswith("role."), "medium",
               "Escalation to a role, not a person", f"escalation_path = {gr.get('escalation_path')}",
               "Route escalations to a role so coverage survives turnover (§04)."),
            _c("cm_04", bool(gr.get("rate_limit")), "low", "Rate limit set",
               f"rate_limit = {gr.get('rate_limit')}", "Bound action frequency to contain a looping agent (§04)."),
            _c("cm_12", reviewed, "medium", "Reviewed (not a bare default)",
               ("reviewed by " + gr["review"]["reviewed_by"]) if reviewed else "unreviewed default",
               "Have the process/QMS owner review & sign off this guardrail (§12 coverage)."),
        ]
        return _wrap(f"Guardrail {gid} v{gr.get('version')}", "guardrail", checks)

    # ---- task ------------------------------------------------------------
    def task(self, tid: str) -> dict:
        t = self.g.get("Task", tid)
        if not t:
            return {"error": f"unknown task {tid}"}
        agents = [w for w in t.get("performed_by", []) if w.startswith("agent.")]
        gr, pinned = self.g.effective_guardrail(tid)
        checks = [
            _c("least_privilege", bool(t.get("data_scope")), "medium", "Data scope declared",
               f"scope = {t.get('data_scope') or 'none'}", "Declare the fields this step may touch (least privilege)."),
            _c("iso9001_44", bool(t.get("performed_by")), "high", "Has a performer",
               f"performed_by = {t.get('performed_by')}", "Assign a role and/or agent to the step."),
            _c("cm_04", (not agents) or bool(gr), "high", "Agent step is guarded (fail-closed)",
               (f"agent {agents} under {pinned}" if agents else "human-only step"),
               "An agent-bound step with no effective guardrail is a defect — attach one (§04)."),
            _c("iso9001_44", len(t.get("name", "")) > 4, "info", "Descriptive step name",
               f'"{t.get("name")}"', "Give the step a clear, action-oriented name."),
        ]
        return _wrap(f"Task {tid} — {t.get('name')}", "task", checks)

    # ---- arbitrary content / data (ISO 9001 §7.5) ------------------------
    def content(self, text: str) -> dict:
        text = text or ""
        low = text.lower()
        # if it parses as JSON matching an entity, validate structurally instead
        stripped = text.strip()
        if stripped[:1] in "{[":
            return self._data(stripped)
        elements = [
            ("iso9001_75", "purpose / scope", r"\b(purpose|scope|objective)\b", "low"),
            ("iso9001_75", "responsible owner", r"\b(owner|responsible|accountable|raci)\b", "medium"),
            ("iso9001_75", "version / revision", r"\b(version|revision|\brev\b|\bv\d)\b", "medium"),
            ("iso9001_75", "review / approval", r"\b(review|approv|effective date|revised)\b", "medium"),
            ("iso9001_44", "inputs named", r"\b(input|inputs|precondition)\b", "low"),
            ("iso9001_44", "outputs named", r"\b(output|outputs|deliverable|result)\b", "low"),
            ("cm_11", "exception / escalation path", r"\b(escalat|exception|when.*human|refer to)\b", "low"),
            ("iso9001_753", "retention / disposition", r"\b(retention|retain|dispose|archive|records? kept)\b", "info"),
        ]
        checks = []
        for std, label, pat, sev in elements:
            ok = bool(re.search(pat, low))
            checks.append(_c(std, ok, sev, f"Mentions {label}",
                             "present" if ok else "not found",
                             "" if ok else f"Documented information should state its {label} (§7.5)."))
        checks.append(_c("iso9001_75", len(stripped) >= 60, "info", "Has substantive content",
                         f"{len(stripped)} chars", "Very short — confirm this is the whole document."))
        note = ("Heuristic check of a document against ISO 9001 §7.5 documented-information "
                "expectations. Presence, not correctness — a human (or the LLM advisor) judges quality.")
        return _wrap("Pasted content", "content", checks, note)

    def _data(self, text: str) -> dict:
        import json
        from jsonschema import Draft202012Validator
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as e:
            return _wrap("Pasted data", "data",
                         [_c("iso9001_75", False, "medium", "Valid JSON", f"parse error: {e}",
                             "Fix the JSON so it can be validated.")])
        # guess the entity type from id/fields, validate against the locked schema
        schema_dir = os.path.normpath(os.path.join(HERE, "..", "schema"))
        guess = None
        if isinstance(obj, dict):
            gid = str(obj.get("id", ""))
            guess = ("guardrail-policy" if gid.startswith("gr.") else
                     "strategic-objective" if gid.startswith("obj.") else
                     "kpi" if gid.startswith("kpi.") else
                     "process" if re.match(r"^[A-Z]{2}\.[0-9.]+$", gid) else
                     "task" if re.match(r"^[A-Z]{2}\.[0-9.]+\.t[0-9]+$", gid) else None)
        checks = [_c("iso9001_75", True, "info", "Valid JSON", "parsed ok", "")]
        if guess:
            with open(os.path.join(schema_dir, f"{guess}.schema.json")) as f:
                v = Draft202012Validator(json.load(f))
            errs = sorted(v.iter_errors(obj), key=lambda e: list(e.path))
            checks.append(_c("apqc", not errs, "high", f"Validates as {guess}",
                             "conforms to the locked schema" if not errs
                             else "; ".join(f"{list(e.path) or '(root)'}: {e.message}" for e in errs[:3]),
                             "" if not errs else "Fix the fields so it matches the Phase-1 data model."))
        else:
            checks.append(_c("iso9001_75", False, "info", "Recognized entity",
                             "id doesn't match a known entity prefix",
                             "Give it an id like gr./obj./kpi./<APQC code> to validate against a schema."))
        return _wrap("Pasted data (JSON)", "data", checks)

    # ---- whole model -----------------------------------------------------
    def model(self) -> dict:
        procs = [p for p in self.g.all("Process") if p["status"] == "active"]
        pscores = [self.process(p["id"])["score"] for p in procs]
        findings = trace.lint(self.g)
        tc = round(trace.completeness_score(self.g, findings) * 100)
        cov = Rollup(self.g).coverage()
        checks = [
            _c("cm_12", not [f for f in findings if f["severity"] == "ERROR"], "high",
               "No broken references", f"{sum(1 for f in findings if f['severity']=='ERROR')} error(s)",
               "Resolve broken references before they mislead an agent."),
            _c("cm_12", tc >= 100, "medium", "Full strategy traceability",
               f"{tc}% of processes trace to strategy", "Give every process a KPI that reaches an objective (§12)."),
            _c("cm_12", cov["pct"] >= 100, "medium", "Guardrail coverage",
               f"{cov['reviewed']}/{cov['total_agent_tasks']} agent steps under a reviewed guardrail ({cov['pct']}%)",
               "Review the default guardrails so coverage rises (§12)."),
            _c("iso9004", (sum(pscores) / (len(pscores) or 1)) >= 80, "low", "Process design health",
               f"avg process score {round(sum(pscores)/(len(pscores) or 1))}% across {len(procs)} processes",
               "Address the lowest-scoring processes (analyze each for detail)."),
        ]
        w = _wrap(f"Whole model ({len(procs)} processes)", "model", checks,
                  "Roll-up scorecard. Analyze a specific process/guardrail for line-by-line findings.")
        w["worst"] = sorted(({"id": p["id"], "score": s} for p, s in zip(procs, pscores)),
                            key=lambda x: x["score"])[:3]
        return w

    # ---- dispatch --------------------------------------------------------
    def analyze(self, subject_type: str, ident: str = "", content: str = "") -> dict:
        if subject_type == "process":
            return self.process(ident)
        if subject_type == "guardrail":
            return self.guardrail(ident)
        if subject_type == "task":
            return self.task(ident)
        if subject_type == "content":
            return self.content(content)
        if subject_type == "model":
            return self.model()
        return {"error": f"unknown subject type {subject_type}"}


class LLMAdvisor:
    """The deeper natural-language reviewer — nuance the rule set can't reach
    (does this guardrail's wording match its intent? is this SOP actually clear?).
    Requires model access (API/OAuth), unavailable in this build, so it is declared
    and refuses rather than pretending — exactly like the signal connectors. The
    RulesAdvisor stands in; swap this in once model access is provisioned."""
    def analyze(self, *a, **k):
        raise RuntimeError("LLMAdvisor requires model access (API key / OAuth), "
                           "unavailable in this build. RulesAdvisor stands in.")


if __name__ == "__main__":
    a = RulesAdvisor()
    import json
    print(json.dumps(a.guardrail("gr.CO.3.2.7"), indent=2)[:1200])
