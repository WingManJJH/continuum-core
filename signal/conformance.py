"""
Conformance Check — Phase 3 (Core Model §06 Figure 4, §09 Phase 3).

The "Check" in Plan-Do-Check-Act: compare the documented model against reality —
external activity from the signal layer plus every agent's own execution log —
and surface where they diverge. Per §06, drift is SURFACED, never auto-applied:
a human closes the loop (the "Act"). So every finding is advisory and carries a
proposed resolution and requires_human_review=True; nothing here writes to the
model.

Also the guardrail early-warning system (§06): an agent operating correctly
against a STALE guardrail is a compliance risk before anyone notices the process
changed, so agent-log conformance checks the guardrails against themselves.

Drift types:
  stale_guardrail    an agent action cited a policy version older than current
  off_model_action   an agent successfully did an action its policy doesn't list
  coverage_gap       observed activity uses an action neither allowed nor forbidden
  undocumented_step  observed a task id not in the model
  shadow_process     observed activity in a process not in the model

    python3 conformance.py            # human report over the sample fixtures
    python3 conformance.py --json     # machine-readable
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
import continuum_core as cc  # noqa: E402
import connectors as conn  # noqa: E402

SEVERITY = {"stale_guardrail": "HIGH", "off_model_action": "HIGH",
            "shadow_process": "MEDIUM", "undocumented_step": "MEDIUM",
            "coverage_gap": "LOW"}
RESOLUTION = {
    "stale_guardrail": "Re-pin the agent to the current policy version, or investigate why it ran stale.",
    "off_model_action": "Human: add the action to the guardrail's allow/deny list, or stop the agent doing it.",
    "coverage_gap": "Human: classify this action in the guardrail (allow or forbid) so the policy covers it.",
    "undocumented_step": "Human: add this step to the process, or investigate the off-model activity.",
    "shadow_process": "Human: model this process (APQC-classify + owner + guardrail), or stop the shadow activity.",
}


def _finding(kind, subject, detail, source):
    return {"type": kind, "severity": SEVERITY[kind], "subject": subject,
            "detail": detail, "source": source,
            "proposed_resolution": RESOLUTION[kind], "requires_human_review": True}


class ConformanceCheck:
    def __init__(self, graph: cc.Graph | None = None):
        self.g = graph or cc.Graph()

    def run(self, signals: list[dict], agent_events: list[dict]) -> dict:
        findings: list[dict] = []
        findings += self._check_agent_log(agent_events)
        findings += self._check_signals(signals)

        counts: dict[str, int] = {}
        for f in findings:
            counts[f["type"]] = counts.get(f["type"], 0) + 1
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "model_sig": self.g.model_sig,
            "counts": counts,
            "n_findings": len(findings),
            "findings": sorted(findings, key=lambda f: (f["severity"], f["type"])),
            "note": "Drift is surfaced for human review; nothing is auto-applied (§06). "
                    "A human closes the loop (the 'Act' in PDCA).",
        }

    # agent execution log → stale guardrail + off-model action (§06 self-check)
    def _check_agent_log(self, events: list[dict]) -> list[dict]:
        out = []
        for e in events:
            task = e.get("entity_id")
            p = e.get("payload", {})
            gr, pinned = self.g.effective_guardrail(task) if task else (None, None)
            cited = p.get("guardrail_version")
            if cited and pinned and cited != pinned:
                out.append(_finding("stale_guardrail", task,
                                    f"agent {e.get('actor', {}).get('id', '?')} acted citing {cited}, "
                                    f"current is {pinned}", "agent_log"))
            action = p.get("action")
            if (gr and action and p.get("outcome") == "success"
                    and action not in gr["allowed_actions"]
                    and action not in gr["forbidden_actions"]):
                out.append(_finding("off_model_action", task,
                                    f"agent executed '{action}', not listed in policy {pinned}", "agent_log"))
        return out

    # external signals → shadow process / undocumented step / coverage gap
    def _check_signals(self, signals: list[dict]) -> list[dict]:
        out = []
        for s in signals:
            proc, task, action, src = s.get("process"), s.get("task"), s.get("action"), s.get("source", "?")
            if proc and self.g.get("Process", proc) is None:
                out.append(_finding("shadow_process", proc,
                                    f"activity in unmodeled process {proc} (action '{action}')", src))
                continue
            if task and self.g.get("Task", task) is None:
                out.append(_finding("undocumented_step", task,
                                    f"step {task} not in the model (action '{action}')", src))
                continue
            if task and action:
                gr, pinned = self.g.effective_guardrail(task)
                if gr and action not in gr["allowed_actions"] and action not in gr["forbidden_actions"]:
                    out.append(_finding("coverage_gap", task,
                                        f"observed action '{action}' is neither allowed nor forbidden by {pinned}", src))
        return out


def load_agent_events(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(x) for x in f if x.strip()]


def gather(signal_sources=None, agent_events_path: str | None = None):
    signals = []
    for c in (signal_sources or conn.default_sources()):
        signals += c.read()
    events = load_agent_events(agent_events_path or os.path.join(HERE, "agent_events.sample.jsonl"))
    return signals, events


if __name__ == "__main__":
    signals, events = gather()
    report = ConformanceCheck().run(signals, events)
    if "--json" in sys.argv:
        print(json.dumps(report, indent=2))
        sys.exit(0)
    print("=" * 74)
    print("CONTINUUM CONFORMANCE CHECK (§06) — documented model vs. reality")
    print(f"model_sig {report['model_sig']} · {report['n_findings']} finding(s) · {report['counts']}")
    print("=" * 74)
    for f in report["findings"]:
        print(f"\n[{f['severity']:<6}] {f['type']}  ({f['source']})")
        print(f"    {f['subject']}: {f['detail']}")
        print(f"    → {f['proposed_resolution']}")
    print("\n" + "-" * 74)
    print(report["note"])
