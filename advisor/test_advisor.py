"""Standards-advisor tests (D17). Plain asserts.

    python3 test_advisor.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "mcp_server"))
sys.path.insert(0, HERE)
import continuum_core as cc  # noqa: E402
import advisor  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


def has(r, title, ok=None):
    for c in r["checks"]:
        if c["title"] == title:
            return c["ok"] if ok is None else (c["ok"] == ok)
    return False


def main():
    a = advisor.RulesAdvisor()

    # 1. the signed-off KYC guardrail is exemplary
    r = a.guardrail("gr.CO.3.2.7")
    check("signed-off guardrail scores 100 with no findings", r["score"] == 100 and r["n_findings"] == 0)

    # 2. a guardrail that allows a high-stakes action unattended is flagged HIGH
    g = cc.Graph()
    g._by_type["GuardrailPolicy"]["gr.TEST"] = {
        "id": "gr.TEST", "allowed_actions": ["read_record", "approve"], "forbidden_actions": [],
        "escalate_if": None, "data_scope": [], "escalation_path": "role.x",
        "rate_limit": None, "version": 1, "status": "active"}
    rt = advisor.RulesAdvisor(g).guardrail("gr.TEST")
    hs = next(c for c in rt["checks"] if c["title"].startswith("No high-stakes"))
    check("high-stakes action in allow-list flagged high", not hs["ok"] and hs["severity"] == "high")
    check("empty deny-list flagged", has(rt, "Explicit deny-list", ok=False))
    check("empty data scope flagged (least privilege)", has(rt, "Least-privilege data scope", ok=False))

    # 3. an empty allow-list is useless
    g._by_type["GuardrailPolicy"]["gr.EMPTY"] = dict(g._by_type["GuardrailPolicy"]["gr.TEST"],
                                                     id="gr.EMPTY", allowed_actions=[])
    check("empty allow-list flagged", has(advisor.RulesAdvisor(g).guardrail("gr.EMPTY"), "Has an allow-list", ok=False))

    # 4. the planted dangling process is caught by the §12 check
    hr = a.process("HR.7.2.5")
    check("dangling process flagged: no strategic parent", has(hr, "Traces to a strategic objective", ok=False))
    co = a.process("CO.3.2.7")
    check("well-formed process scores high", co["score"] >= 85 and has(co, "Governed by a guardrail"))

    # 5. task: an agent step must be guarded (fail-closed)
    t3 = a.task("CO.3.2.7.t3")
    check("agent step passes the fail-closed guard check", has(t3, "Agent step is guarded (fail-closed)"))

    # 6. content: a thin SOP misses doc-control elements; a fuller one scores better
    thin = a.content("Verify the document.")
    full = a.content("Purpose: verify KYC. Owner: role.ops.support_lead. Version 3, reviewed 2026-08. "
                     "Inputs: kyc_doc. Outputs: verified flag. Escalate high-risk cases to a human. "
                     "Records retained 7 years.")
    check("thin content scores low on §7.5 elements", thin["score"] < 40)
    check("fuller content scores higher", full["score"] > thin["score"])
    check("content analysis cites ISO 9001 §7.5", any("7.5" in c["standard"] for c in thin["checks"]))

    # 7. pasted JSON routes to schema validation
    d = a.content('{"id":"gr.CO.3.2.7","attaches_to":{"kind":"process","ref":"CO.3.2.7"},'
                  '"allowed_actions":["verify_document"],"forbidden_actions":[],"escalate_if":null,'
                  '"data_scope":[],"rate_limit":{"max_actions":1,"per_seconds":1},'
                  '"escalation_path":"role.x","audit_requirement":"inputs_outputs","version":1,"status":"active"}')
    check("valid guardrail JSON validates against the schema", d["kind"] == "data" and has(d, "Validates as guardrail-policy"))
    bad = a.content('{"id":"gr.BAD","allowed_actions":[]}')
    check("malformed guardrail JSON flagged by the schema", not has(bad, "Validates as guardrail-policy"))

    # 8. whole-model scorecard reflects the real §12 numbers
    m = a.model()
    check("model scorecard reports coverage + traceability", any("Guardrail coverage" == c["title"] for c in m["checks"])
          and any("Full strategy traceability" == c["title"] for c in m["checks"]))
    check("model lists worst-scoring processes", isinstance(m.get("worst"), list) and len(m["worst"]) >= 1)

    # 9. dispatch + errors + the LLM seam
    check("dispatch routes by subject type", a.analyze("guardrail", "gr.CO.3.2.7")["score"] == 100)
    check("unknown subject errors cleanly", "error" in a.analyze("process", "NOPE.0.0.0"))

    # 10. LLMAdvisor is auth-gated: unavailable + review refuses with no key
    la = advisor.LLMAdvisor()
    check("LLMAdvisor reports unavailable with no key", not la.available())
    try:
        la.review("Guardrail x", "guardrail", [], {}); refused = False
    except RuntimeError:
        refused = True
    check("LLMAdvisor.review refuses with no key (auth-gated)", refused)

    # 11. Advisor orchestrator: deterministic-only by default (no key)
    adv = advisor.Advisor()
    r = adv.analyze("guardrail", "gr.CO.3.2.7")
    check("Advisor runs rules only when no key", r["llm_status"] == "off" and r["llm_findings"] == [])
    check("Advisor still returns the deterministic score", r["score"] == 100)

    # 12. full LLM path via injected transport (no key, no network); it AUGMENTS
    def good_transport(system, user):
        return ('[{"severity":"high","title":"Wording invites over-collection",'
                '"detail":"data_scope reads broad","recommendation":"Scope to the two fields used."},'
                '{"severity":"SHOUT","title":"No title-less drop","detail":"x"},'
                '{"detail":"no title so dropped"}]')
    adv2 = advisor.Advisor(llm_transport=good_transport)
    r2 = adv2.analyze("guardrail", "gr.CO.3.2.7")
    check("LLM findings augment the scorecard", r2["llm_status"] == "on" and len(r2["llm_findings"]) == 2)
    check("LLM findings tagged as source=llm", all(f["source"] == "llm" for f in r2["llm_findings"]))
    check("bad severity normalized to info", r2["llm_findings"][1]["severity"] == "info")
    check("LLM review never changes the deterministic score", r2["score"] == 100)

    # 13. a malformed LLM reply falls back honestly; the rules result survives
    adv3 = advisor.Advisor(llm_transport=lambda s, u: "sorry, no JSON here")
    r3 = adv3.analyze("guardrail", "gr.CO.3.2.7")
    check("malformed LLM reply -> status error, rules intact",
          r3["llm_status"] == "error" and r3["score"] == 100 and "llm_note" in r3)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    sys.exit(1 if FAIL else 0)


if __name__ == "__main__":
    main()
