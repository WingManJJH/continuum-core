"""
Token-budget harness — Core Model §13 step 2 / §08.

Validates the four agent-facing payloads against the §08 budgets using a real
tokenizer (tiktoken), not an eyeballed estimate, and shows the compression ratio
vs. an equivalent BPMN-XML export and prose SOP for the same task (§03's "8-15x
more" claim). Also validates the seed graph against the locked schemas.

Methodology note: budgets in §08 are stated in "tokens". Claude's own tokenizer
is not published for local use; tiktoken's o200k_base (GPT-4o family) is used as
a real, close proxy and cl100k_base is reported alongside so the number isn't
tied to one tokenizer. Both land well under budget with margin to spare, so the
conclusion is robust to the small cross-tokenizer difference. For a production
sign-off, swap in Anthropic's count_tokens API — the harness is structured so
that is a one-function change (see count()).

Run:
    python3 token_budget.py            # budget report (exit 1 if any exceeded)
    python3 token_budget.py --validate # schema-validate the seed graph too
"""
from __future__ import annotations

import glob
import json
import os
import sys

import tiktoken

import continuum_core as cc

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_DIR = os.path.normpath(os.path.join(HERE, "..", "schema"))

ENC_PRIMARY = tiktoken.get_encoding("o200k_base")
ENC_ALT = tiktoken.get_encoding("cl100k_base")


def count(text: str) -> int:
    """Primary token count. Swap this body for Anthropic count_tokens to sign off."""
    return len(ENC_PRIMARY.encode(text))


def count_alt(text: str) -> int:
    return len(ENC_ALT.encode(text))


# §08 budgets --------------------------------------------------------------
# Single-task-context raised 150 -> 200 by ratified decision (see ../DECISIONS.md
# D1): the real tokenized package is ~136 and a larger process would breach 150;
# keeping the guardrail inline (the point of §03) is worth the higher ceiling.
BUDGETS = [
    ("Single task context", 200, "get_task_context('CO.3.2.7.t3')"),
    ("Guardrail check response", 40, "check_guardrail(t3, verify_document, risk_score=0.9)"),
    ("Process summary (task list)", 400, "process_summary('CO.3.2.7')"),
    ("Strategy rollup (obj -> KPI)", 250, "strategy_rollup('obj.reduce_onboarding_friction')"),
]


def payloads(g: cc.Graph) -> dict[str, str]:
    verdict = cc.check_guardrail(g, "CO.3.2.7.t3", "verify_document", {"risk_score": 0.9})
    return {
        "Single task context": cc.render_task_context(g, "CO.3.2.7.t3"),
        "Guardrail check response": cc.render_guardrail_check(verdict),
        "Process summary (task list)": cc.render_process_summary(g, "CO.3.2.7"),
        "Strategy rollup (obj -> KPI)": cc.render_strategy_rollup(g, "obj.reduce_onboarding_friction"),
    }


# A hand-built verbose baseline for the SAME task, to measure the compression
# ratio §03 claims. Representative BPMN 2.0 XML + a prose SOP paragraph.
BPMN_XML_BASELINE = """<?xml version="1.0" encoding="UTF-8"?>
<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL"
                  xmlns:bpmndi="http://www.omg.org/spec/BPMN/20100524/DI"
                  xmlns:dc="http://www.omg.org/spec/DD/20100524/DC"
                  targetNamespace="http://continuum.dev/co">
  <bpmn:process id="Process_CO_3_2_7" name="Verify customer identity (KYC)" isExecutable="true">
    <bpmn:userTask id="Task_t3" name="Verify KYC document" camunda:assignee="support_tier1">
      <bpmn:documentation>Verify the customer's submitted KYC document. Allowed actions:
        verify_document, request_resubmit. Do not approve credit limit. Escalate to the
        support lead when the computed risk score exceeds 0.7.</bpmn:documentation>
      <bpmn:extensionElements>
        <camunda:inputOutput>
          <camunda:inputParameter name="customer.kyc_doc" />
          <camunda:inputParameter name="customer.risk_score" />
          <camunda:outputParameter name="customer.verified" />
        </camunda:inputOutput>
      </bpmn:extensionElements>
      <bpmn:incoming>Flow_t2_t3</bpmn:incoming>
      <bpmn:outgoing>Flow_t3_t4</bpmn:outgoing>
    </bpmn:userTask>
  </bpmn:process>
  <bpmndi:BPMNDiagram id="BPMNDiagram_1">
    <bpmndi:BPMNPlane id="BPMNPlane_1" bpmnElement="Process_CO_3_2_7">
      <bpmndi:BPMNShape id="Task_t3_di" bpmnElement="Task_t3">
        <dc:Bounds x="420" y="160" width="100" height="80" />
      </bpmndi:BPMNShape>
    </bpmndi:BPMNPlane>
  </bpmndi:BPMNDiagram>
</bpmn:definitions>"""

SOP_PROSE_BASELINE = (
    "Standard Operating Procedure — KYC Document Verification (Step 3 of the customer "
    "identity verification process). Purpose: This step ensures that the identity "
    "document submitted by the customer during onboarding is genuine and matches the "
    "customer record. Responsibility: This task is normally performed by a Tier 1 "
    "Support Agent, and may be performed by the bound verification agent where "
    "permitted. Inputs: the customer's submitted KYC document. Outputs: a verified "
    "flag on the customer record. Procedure: Review the submitted document for "
    "authenticity. The agent is permitted to mark the document verified or to request "
    "that the customer resubmit a clearer copy. The agent must not, under any "
    "circumstances, approve a credit limit as part of this step. Where the customer's "
    "computed risk score is greater than 0.7, the agent must not finalize verification "
    "and must instead escalate the case to the Support Team Lead for manual review. "
    "All actions taken must be logged with their inputs and outputs, together with the "
    "version of the governing policy in force at the time the action was taken, so that "
    "any subsequent dispute can be resolved against the policy that actually applied."
)


def bar(pct: float, width: int = 24) -> str:
    fill = min(width, int(round(pct / 100 * width)))
    return "[" + "#" * fill + "-" * (width - fill) + "]"


def run_budget_report(g: cc.Graph) -> bool:
    pl = payloads(g)
    print("=" * 78)
    print("CONTINUUM §08 AGENT DATA-EFFICIENCY BUDGET — VALIDATION")
    print("tokenizer: tiktoken o200k_base (primary) | cl100k_base (alt)")
    print("=" * 78)
    print(f"{'payload':<30}{'tokens':>7}{'budget':>8}{'use':>6}  status")
    print("-" * 78)
    all_ok = True
    for name, budget, _call in BUDGETS:
        text = pl[name]
        n = count(text)
        pct = n / budget * 100
        ok = n <= budget
        all_ok &= ok
        flag = "PASS" if ok else "FAIL"
        print(f"{name:<30}{n:>7}{budget:>8}{pct:>5.0f}%  {flag}  {bar(pct)}")
    print("-" * 78)
    print("alt tokenizer (cl100k_base) cross-check:")
    for name, budget, _ in BUDGETS:
        n2 = count_alt(pl[name])
        print(f"  {name:<30}{n2:>7} / {budget}")

    print("\n" + "=" * 78)
    print("COMPRESSION vs. verbose representations (same task, §03 '8-15x' claim)")
    print("=" * 78)
    ctx = pl["Single task context"]
    ctx_tok = count(ctx)
    for label, baseline in (("BPMN 2.0 XML export", BPMN_XML_BASELINE),
                            ("Prose SOP paragraph", SOP_PROSE_BASELINE)):
        b = count(baseline)
        print(f"  {label:<22}{b:>6} tok   ->  context package {ctx_tok:>3} tok   "
              f"({b / ctx_tok:.1f}x smaller)")
    print("=" * 78)
    print(f"\nRESULT: {'ALL BUDGETS PASS' if all_ok else 'BUDGET EXCEEDED'}")
    return all_ok


def run_worstcase_sweep(g: cc.Graph) -> bool:
    """Stress the budgets across the WHOLE graph, not just the CO example —
    the point of widening the seed to 8 domains. Reports the largest payload of
    each kind and which entity produced it."""
    task_budget = dict((n, b) for n, b, _ in BUDGETS)["Single task context"]
    proc_budget = dict((n, b) for n, b, _ in BUDGETS)["Process summary (task list)"]
    obj_budget = dict((n, b) for n, b, _ in BUDGETS)["Strategy rollup (obj -> KPI)"]

    tasks = [(t["id"], count(cc.render_task_context(g, t["id"]))) for t in g.all("Task")]
    procs = [(p["id"], count(cc.render_process_summary(g, p["id"]))) for p in g.all("Process")]
    objs = [(o["id"], count(cc.render_strategy_rollup(g, o["id"]))) for o in g.all("StrategicObjective")]

    print("\n" + "=" * 78)
    print(f"WORST-CASE SWEEP across the whole graph "
          f"({len(tasks)} tasks, {len(procs)} processes, {len(objs)} objectives)")
    print("=" * 78)
    ok = True
    for label, rows, budget in (("task context", tasks, task_budget),
                                ("process summary", procs, proc_budget),
                                ("strategy rollup", objs, obj_budget)):
        worst_id, worst = max(rows, key=lambda r: r[1])
        mean = sum(n for _, n in rows) / len(rows)
        good = worst <= budget
        ok &= good
        print(f"  {label:<16} max {worst:>3}/{budget:<3} ({worst_id:<14}) "
              f"mean {mean:>5.1f}  {'PASS' if good else 'FAIL'}")
    print("-" * 78)
    print("WORST-CASE SWEEP:", "ALL UNDER BUDGET" if ok else "BUDGET EXCEEDED")
    return ok


def validate_seed(g_path: str = cc.DATA) -> bool:
    from jsonschema import Draft202012Validator

    with open(g_path) as f:
        raw = json.load(f)
    schemas = {}
    for p in glob.glob(os.path.join(SCHEMA_DIR, "*.schema.json")):
        with open(p) as f:
            s = json.load(f)
        schemas[s["title"]] = s
    type_to_title = {
        "StrategicObjective": "Strategic Objective", "KPI": "KPI",
        "Process": "Process", "Task": "Task / Activity",
        "HumanRole": "Human Role", "AgentBinding": "Agent Binding",
        "GuardrailPolicy": "Guardrail Policy", "RiskControl": "Risk & Control",
    }
    ok = True
    print("=" * 78)
    print("SCHEMA VALIDATION — seed graph against locked schemas")
    print("=" * 78)
    for etype, title in type_to_title.items():
        v = Draft202012Validator(schemas[title])
        for obj in raw.get(etype, []):
            errs = sorted(v.iter_errors(obj), key=lambda e: e.path)
            if errs:
                ok = False
                for e in errs:
                    print(f"  FAIL {etype} {obj.get('id')}: {list(e.path)} {e.message}")
            else:
                print(f"  ok   {etype:<20} {obj.get('id')}")
    print("-" * 78)
    print("SCHEMA VALIDATION:", "ALL VALID" if ok else "INVALID")
    return ok


if __name__ == "__main__":
    g = cc.Graph()
    schema_ok = True
    if "--validate" in sys.argv:
        schema_ok = validate_seed()
        print()
    budget_ok = run_budget_report(g)
    sweep_ok = run_worstcase_sweep(g)
    sys.exit(0 if (schema_ok and budget_ok and sweep_ok) else 1)
