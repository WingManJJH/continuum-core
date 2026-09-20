"""
CAPA — Corrective / Preventive Action register (Core Model §07/§10, ISO 9001 §10.2).

Turns "every reported error is corrected under control" into a real workflow. A
nonconformity — a failed audit, a customer complaint, a KPI breach, an agent
escalation, an incident — becomes a **Corrective Action Request (CAR)**: a governed
record with an accountable owner, the processes it affects, a due date, root cause,
corrective + preventive action, and an effectiveness check. The set of CARs is the
corrective-action register.

A CAR is a first-class graph entity, so it rides the SAME machinery everything else
in Continuum does:
  - every raise / edit / state change is a new version on the hash-chained
    change-control log (ISO 9001 §7.5) — the register keeps its own audit trail;
  - it folds into the one graph the agent, dashboard, canvas, and advisor all read,
    so the register, the process flags on the canvas, the owner notifications, and
    the AI insights are all the same source of truth.

This module is the write + read layer, mirroring GovernanceStore: validate against
the LOCKED schema, enforce the lifecycle, bump the version, append one immutable
event. Stdlib + jsonschema only, so it is testable on its own.
"""
from __future__ import annotations

import copy
import json
import os
import sys
from datetime import date, datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402

from jsonschema import Draft202012Validator  # noqa: E402
from store import EditError  # noqa: E402  — reuse so app.py's handler catches CAPA errors too

SCHEMA_DIR = os.path.normpath(os.path.join(HERE, "..", "schema"))

# The corrective-action lifecycle. A CAR moves forward through it, can step back
# (a verify that fails returns to action_planned), can be cancelled while live, and
# a closed CAR can be reopened if the problem recurs. 'closed'/'cancelled' terminal.
TRANSITIONS = {
    "open":           {"investigating", "cancelled"},
    "investigating":  {"action_planned", "open", "cancelled"},
    "action_planned": {"implemented", "investigating", "cancelled"},
    "implemented":    {"verifying", "action_planned", "cancelled"},
    "verifying":      {"closed", "action_planned", "cancelled"},
    "closed":         {"investigating"},   # reopen on recurrence / ineffective closure
    "cancelled":      set(),
}
TERMINAL = {"closed", "cancelled"}
SEVERITY_RANK = {"minor": 1, "major": 2, "critical": 3}

EDITABLE_FIELDS = [
    "title", "nonconformance", "source", "severity", "affected_process_refs",
    "owner_role", "date_due", "containment", "root_cause", "corrective_action",
    "preventive_action", "effectiveness_check", "risk_refs", "related_car_refs", "custom",
]


class CAPAError(EditError):
    """A rejected CAPA change — the reason is safe to show the owner in the UI."""


def _today() -> str:
    return date.today().isoformat()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _days_between(a: str, b: str) -> int | None:
    try:
        return (date.fromisoformat(b) - date.fromisoformat(a)).days
    except (ValueError, TypeError):
        return None


class CAPAStore:
    def __init__(self):
        with open(os.path.join(SCHEMA_DIR, "corrective-action.schema.json")) as f:
            self._validator = Draft202012Validator(json.load(f))

    def graph(self) -> cc.Graph:
        return cc.Graph()  # folds seed + edit log every load (respects the active model)

    # --- helpers -----------------------------------------------------------
    def _require(self, reason: str, actor: str) -> None:
        if not reason or not reason.strip():
            raise CAPAError("a change reason is required (ISO 9001 §7.5 review trail)")
        if not actor or not actor.startswith("role."):
            raise CAPAError("actor must be a role (e.g. role.qms.iso_advisor)")

    def _validate(self, car: dict) -> None:
        errs = sorted(self._validator.iter_errors(car), key=lambda e: list(e.path))
        if errs:
            raise CAPAError("; ".join(f"{list(e.path) or '(root)'}: {e.message}" for e in errs[:4]))

    def _check_refs(self, g: cc.Graph, car: dict) -> None:
        if g.get("HumanRole", car["owner_role"]) is None:
            raise CAPAError(f"unknown owner role {car['owner_role']}")
        for pid in car.get("affected_process_refs", []):
            if g.get("Process", pid) is None:
                raise CAPAError(f"unknown affected process {pid}")
        for rr in car.get("risk_refs", []):
            if g.get("RiskControl", rr) is None:
                raise CAPAError(f"unknown risk & control {rr}")
        for cr in car.get("related_car_refs", []):
            if g.get("CorrectiveAction", cr) is None:
                raise CAPAError(f"unknown related CAR {cr}")

    def _next_id(self, g: cc.Graph, when: str) -> str:
        """car.<year>.<NNN> — the next free sequence for the year (never reused)."""
        year = when[:4]
        prefix = f"car.{year}."
        used = 0
        for c in g.all("CorrectiveAction"):
            cid = c["id"]
            if cid.startswith(prefix):
                tail = cid[len(prefix):]
                if tail.isdigit():
                    used = max(used, int(tail))
        return f"{prefix}{used + 1:03d}"

    # --- writes ------------------------------------------------------------
    def raise_car(self, title: str, nonconformance: str, source: str, severity: str,
                  owner_role: str, affected_process_refs: list, actor: str, reason: str,
                  date_due: str | None = None, containment: str = "",
                  risk_refs: list | None = None, date_raised: str | None = None) -> dict:
        """Open a new CAR for a reported error. It is stamped with a CAR number,
        date-raised, state=open, and recorded as a versioned, chained event."""
        self._require(reason, actor)
        if not title or not title.strip():
            raise CAPAError("a title is required")
        if not nonconformance or not nonconformance.strip():
            raise CAPAError("describe the nonconformity (what went wrong)")
        g = self.graph()
        raised = date_raised or _today()
        car = {
            "id": self._next_id(g, raised),
            "title": title.strip(), "nonconformance": nonconformance.strip(),
            "source": source, "severity": severity, "state": "open",
            "owner_role": owner_role, "date_raised": raised,
            "date_due": (date_due or None), "date_closed": None,
            "affected_process_refs": list(affected_process_refs or []),
            "containment": (containment or "").strip(),
            "root_cause": "", "corrective_action": "", "preventive_action": "",
            "effectiveness_check": "", "risk_refs": list(risk_refs or []),
            "related_car_refs": [], "custom": {}, "version": 1, "status": "active",
        }
        self._validate(car)
        self._check_refs(g, car)
        cc.append_edit_event("CorrectiveAction", car["id"], "create", None, 1,
                             {"kind": "human", "id": actor}, car, reason.strip())
        return car

    def edit_car(self, car_id: str, changes: dict, actor: str, reason: str) -> dict:
        """Edit CAR content — the investigation and action fields, owner, due date,
        affected processes. The lifecycle `state` has its own path (transition)."""
        self._require(reason, actor)
        g = self.graph()
        cur = g.get("CorrectiveAction", car_id)
        if cur is None or cur["status"] != "active":
            raise CAPAError(f"unknown or retired CAR {car_id}")
        unknown = set(changes) - set(EDITABLE_FIELDS)
        if unknown:
            raise CAPAError(f"these fields are not editable here (state has its own path): {sorted(unknown)}")
        new = copy.deepcopy(cur)
        for k, v in changes.items():
            if k in ("title", "nonconformance", "containment", "root_cause", "corrective_action",
                     "preventive_action", "effectiveness_check"):
                new[k] = str(v or "").strip()
            elif k in ("affected_process_refs", "risk_refs", "related_car_refs"):
                new[k] = list(v or [])
            elif k == "date_due":
                new[k] = (str(v).strip() or None) if v else None
            else:
                new[k] = v
        new["version"] = cur["version"] + 1
        self._validate(new)
        self._check_refs(g, new)
        cc.append_edit_event("CorrectiveAction", car_id, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor}, new, reason.strip())
        return new

    def transition(self, car_id: str, to_state: str, actor: str, reason: str) -> dict:
        """Move a CAR through the corrective-action lifecycle. Enforces the allowed
        transitions and the §10.2 discipline: a root cause before an action plan, a
        corrective action and an effectiveness check before closure. Sets/clears
        date_closed at the terminal boundary. Versioned + chained."""
        self._require(reason, actor)
        g = self.graph()
        cur = g.get("CorrectiveAction", car_id)
        if cur is None or cur["status"] != "active":
            raise CAPAError(f"unknown or retired CAR {car_id}")
        frm = cur["state"]
        if to_state == frm:
            raise CAPAError(f"CAR {car_id} is already {frm}")
        if to_state not in TRANSITIONS.get(frm, set()):
            allowed = ", ".join(sorted(TRANSITIONS.get(frm, set()))) or "nothing (terminal)"
            raise CAPAError(f"cannot move a {frm} CAR to {to_state}; allowed: {allowed}")
        # §10.2 gates — a CAR can't skip the discipline it exists to enforce
        if to_state == "action_planned" and not cur.get("root_cause", "").strip():
            raise CAPAError("record a root cause before planning corrective action (§10.2)")
        if to_state == "closed":
            if not cur.get("corrective_action", "").strip():
                raise CAPAError("record the corrective action before closing (§10.2)")
            if not cur.get("effectiveness_check", "").strip():
                raise CAPAError("record an effectiveness check before closing (§10.2 — verify it worked)")
        new = copy.deepcopy(cur)
        new["state"] = to_state
        new["date_closed"] = _today() if to_state in TERMINAL else None
        new["version"] = cur["version"] + 1
        self._validate(new)
        cc.append_edit_event("CorrectiveAction", car_id, "update", cur["version"], new["version"],
                             {"kind": "human", "id": actor},
                             new, f"{reason.strip()} [{frm} → {to_state}]")
        return new

    # --- reads -------------------------------------------------------------
    def _enrich(self, g: cc.Graph, c: dict, today: str) -> dict:
        pnames = {p["id"]: p for p in g.all("Process")}
        closed = c["state"] in TERMINAL
        overdue = bool(c.get("date_due") and not closed
                       and (_days_between(today, c["date_due"]) or 0) < 0)
        age = _days_between(c["date_raised"], c.get("date_closed") or today)
        affected = [{"id": pid, "name": pnames[pid]["name"] if pid in pnames else pid,
                     "owner": pnames[pid]["owner_role"] if pid in pnames else None}
                    for pid in c.get("affected_process_refs", [])]
        return {**c, "closed": closed, "overdue": overdue, "age_days": age,
                "days_to_due": _days_between(today, c["date_due"]) if c.get("date_due") else None,
                "affected": affected}

    def register(self, g: cc.Graph | None = None, today: str | None = None) -> list[dict]:
        """The whole corrective-action register, newest first, each row enriched with
        overdue / age / affected-process names + owners for display."""
        g = g or self.graph()
        today = today or _today()
        rows = [self._enrich(g, c, today) for c in g.all("CorrectiveAction") if c["status"] == "active"]
        return sorted(rows, key=lambda c: c["date_raised"], reverse=True)

    def open_cars(self, g: cc.Graph | None = None, today: str | None = None) -> list[dict]:
        return [c for c in self.register(g, today) if not c["closed"]]

    def for_process(self, pid: str, g: cc.Graph | None = None, today: str | None = None) -> list[dict]:
        """Every active CAR that names `pid` among its affected processes."""
        return [c for c in self.register(g, today) if pid in c.get("affected_process_refs", [])]

    def process_flags(self, g: cc.Graph | None = None, today: str | None = None) -> dict:
        """{process_id: {open, overdue, severity, cars:[...]}} for OPEN CARs — so the
        canvas / landscape can flag exactly where corrective action is in flight."""
        g = g or self.graph()
        flags: dict[str, dict] = {}
        for c in self.open_cars(g, today):
            for pid in c.get("affected_process_refs", []):
                f = flags.setdefault(pid, {"open": 0, "overdue": 0, "severity": "minor", "cars": []})
                f["open"] += 1
                f["overdue"] += 1 if c["overdue"] else 0
                if SEVERITY_RANK[c["severity"]] > SEVERITY_RANK[f["severity"]]:
                    f["severity"] = c["severity"]
                f["cars"].append({"id": c["id"], "title": c["title"], "state": c["state"],
                                  "severity": c["severity"], "overdue": c["overdue"]})
        return flags

    def notifications(self, g: cc.Graph | None = None, today: str | None = None) -> dict:
        """Who needs to act, and why. For every open CAR: the CAR owner (drive it to
        closure) and each affected process's owner (a nonconformity touches your
        process). Overdue CARs are marked so the UI can escalate them. Returns
        {items:[...], by_role:{role:[items]}} — the raw material for owner alerts."""
        g = g or self.graph()
        today = today or _today()
        items = []
        for c in self.open_cars(g, today):
            base = {"car_id": c["id"], "title": c["title"], "severity": c["severity"],
                    "state": c["state"], "date_due": c.get("date_due"), "overdue": c["overdue"]}
            items.append({**base, "role": c["owner_role"], "kind": "owner", "process": None})
            for a in c["affected"]:
                if a["owner"] and a["owner"] != c["owner_role"]:
                    items.append({**base, "role": a["owner"], "kind": "affected_process",
                                  "process": a["id"], "process_name": a["name"]})
        by_role: dict[str, list] = {}
        for it in items:
            by_role.setdefault(it["role"], []).append(it)
        return {"items": items, "by_role": by_role,
                "roles_to_notify": sorted(by_role), "overdue": sum(1 for i in items if i["overdue"])}

    def insights(self, g: cc.Graph | None = None, today: str | None = None) -> list[dict]:
        """Deterministic CAPA findings for the AI-insights layer — same shape the
        advisor uses ({severity,title,detail,recommendation}). Surfaces overdue and
        critical open CARs, recurrence hotspots (a process carrying several), aging
        CARs, and systemic causes (a root cause repeating across CARs)."""
        g = g or self.graph()
        today = today or _today()
        rows = self.register(g, today)
        openc = [c for c in rows if not c["closed"]]
        out = []

        overdue = [c for c in openc if c["overdue"]]
        if overdue:
            out.append(_finding("high", f"{len(overdue)} corrective action(s) overdue",
                                "; ".join(f"{c['id']} ({c['title']}) due {c['date_due']}" for c in overdue[:4]),
                                "Reassign or escalate to the CAR owners so past-due nonconformities close."))
        crit = [c for c in openc if c["severity"] == "critical"]
        if crit:
            out.append(_finding("high", f"{len(crit)} critical CAR(s) still open",
                                "; ".join(f"{c['id']} — {c['title']}" for c in crit[:4]),
                                "Critical nonconformities should be contained and closed first."))
        # recurrence hotspot: one process carrying several open CARs
        by_proc: dict[str, list] = {}
        for c in openc:
            for pid in c.get("affected_process_refs", []):
                by_proc.setdefault(pid, []).append(c["id"])
        hot = sorted(((pid, ids) for pid, ids in by_proc.items() if len(ids) >= 2),
                     key=lambda x: -len(x[1]))
        for pid, ids in hot[:3]:
            proc = g.get("Process", pid)
            out.append(_finding("medium", f"Recurrence hotspot: {pid} has {len(ids)} open CARs",
                                f"{(proc['name'] + ' — ') if proc else ''}{', '.join(ids)}",
                                "Repeated nonconformities on one process point to a systemic cause — review the process design, not just each incident."))
        # aging: open a long time
        aging = [c for c in openc if (c["age_days"] or 0) > 60]
        if aging:
            out.append(_finding("medium", f"{len(aging)} CAR(s) open longer than 60 days",
                                "; ".join(f"{c['id']} ({c['age_days']}d)" for c in aging[:4]),
                                "Long-running CARs stall the corrective-action cycle — set due dates and drive them."))
        # systemic: the same root cause across multiple CARs
        causes: dict[str, list] = {}
        for c in rows:
            rc = (c.get("root_cause") or "").strip().lower()
            if len(rc) >= 12:
                causes.setdefault(rc, []).append(c["id"])
        for rc, ids in causes.items():
            if len(ids) >= 2:
                out.append(_finding("medium", "A root cause repeats across CARs",
                                    f"{len(ids)} CARs share a root cause: {', '.join(ids)}",
                                    "A recurring root cause is a preventive-action opportunity — fix the class of problem once."))
        # discipline: in action but no root cause captured (shouldn't happen via the gate)
        no_rc = [c for c in openc if c["state"] in ("action_planned", "implemented", "verifying")
                 and not (c.get("root_cause") or "").strip()]
        if no_rc:
            out.append(_finding("low", f"{len(no_rc)} CAR(s) in action without a recorded root cause",
                                "; ".join(c["id"] for c in no_rc[:4]),
                                "Record the root cause so the corrective action addresses the cause, not the symptom."))
        return out

    def summary(self, g: cc.Graph | None = None, today: str | None = None) -> dict:
        """Headline counts for the register (open / overdue / by-state / by-severity)."""
        g = g or self.graph()
        today = today or _today()
        rows = self.register(g, today)
        openc = [c for c in rows if not c["closed"]]
        by_state: dict[str, int] = {}
        for c in rows:
            by_state[c["state"]] = by_state.get(c["state"], 0) + 1
        return {"total": len(rows), "open": len(openc),
                "overdue": sum(1 for c in openc if c["overdue"]),
                "critical_open": sum(1 for c in openc if c["severity"] == "critical"),
                "by_state": by_state}


def _finding(severity: str, title: str, detail: str, recommendation: str) -> dict:
    return {"source": "capa", "severity": severity, "title": title,
            "detail": detail, "recommendation": recommendation}


if __name__ == "__main__":
    s = CAPAStore()
    print(json.dumps(s.summary(), indent=2))
    print(json.dumps(s.insights(), indent=2)[:1200])
