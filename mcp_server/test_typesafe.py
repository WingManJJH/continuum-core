"""System One (Jev) seam tests. Plain asserts, hermetic — an injected transport
runs the whole path with no key and no network.

    python3 mcp_server/test_typesafe.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import typesafe as ts  # noqa: E402

PASS, FAIL = [], []


def check(name, cond):
    (PASS if cond else FAIL).append(name)
    print(f"  {'ok  ' if cond else 'FAIL'} {name}")


QS = [
    {"id": "risk", "kind": "score", "scale": [1, 5], "prompt": "operational risk"},
    {"id": "customer_facing", "kind": "noul", "prompt": "is it customer-facing?"},
    {"id": "owner", "kind": "choice", "options": ["role.ops", "role.fin"], "prompt": "likely owner"},
]


def main():
    os.environ.pop(ts.API_KEY_ENV, None)  # ensure no ambient key

    # availability
    check("unavailable with no key and no transport", ts.available() is False)
    check("available with an injected transport", ts.available(lambda s, q: {}) is True)

    # a well-formed transport returns typed, coerced answers
    def good(state, questions):
        return {"risk": {"score": 4, "confidence": 0.8},
                "customer_facing": {"noul": 0.9},
                "owner": {"value": "role.fin", "confidence": 0.7, "probabilities": {"role.fin": 0.7, "role.ops": 0.3}}}
    ans = ts.decide({"name": "Invoice approval"}, QS, transport=good)
    check("score returned", ans["risk"]["score"] == 4)
    check("noul returned", ans["customer_facing"]["noul"] == 0.9)
    check("choice returned", ans["owner"]["value"] == "role.fin")

    # defensive coercion: out-of-type answers can never reach the model
    def bad(state, questions):
        return {"risk": {"score": 99},                       # above scale
                "customer_facing": {"noul": 5},              # above 1
                "owner": {"value": "role.nonexistent"}}      # not in options
    ans2 = ts.decide({}, QS, transport=bad)
    check("score clamped to scale max", ans2["risk"]["score"] == 5)
    check("noul clamped to 1.0", ans2["customer_facing"]["noul"] == 1.0)
    check("invalid choice rejected -> falls back into options", ans2["owner"]["value"] in ["role.ops", "role.fin"])

    # invalid choice with probabilities -> picks the highest valid one
    def probby(state, questions):
        return {"owner": {"value": "??", "probabilities": {"role.ops": 0.6, "role.fin": 0.4}}}
    a3 = ts.decide({}, [QS[2]], transport=probby)
    check("invalid choice resolves via probabilities", a3["owner"]["value"] == "role.ops")

    # a missing answer still coerces to a valid in-type default
    a4 = ts.decide({}, QS, transport=lambda s, q: {})
    check("missing answers default in-type", a4["risk"]["score"] == 1 and a4["customer_facing"]["noul"] == 0.0 and a4["owner"]["value"] in ["role.ops", "role.fin"])

    # malformed questions are refused up front
    for bad_q in [[], [{"id": "x", "kind": "bogus"}],
                  [{"id": "c", "kind": "choice"}],                    # no options
                  [{"id": "s", "kind": "score", "scale": [5, 1]}],    # lo >= hi
                  [{"id": "a", "kind": "noul"}, {"id": "a", "kind": "noul"}]]:  # dup id
        try:
            ts.decide({}, bad_q, transport=lambda s, q: {})
            check("malformed questions refused", False)
        except ts.QuestionError:
            check("malformed questions refused", True)

    # no key + no transport -> refuses (callers fall back)
    try:
        ts.decide({}, QS)
        check("refuses with no access", False)
    except RuntimeError:
        check("refuses with no access", True)

    # --- wire translation to the real /v1/systemone contract (pure, no network) ---
    scored = [{"id": "sev", "kind": "score", "scale": [1, 5],
               "prompt": "how severe?", "levels": ["tiny", "small", "moderate", "big", "huge"]},
              {"id": "cust", "kind": "noul", "prompt": "customer-facing?",
               "true": "touches a customer", "false": "internal only"},
              {"id": "own", "kind": "choice", "options": ["a", "b"],
               "prompt": "owner?", "option_desc": {"a": "team A", "b": "team B"}}]
    api_q = ts._to_api_questions(scored)
    check("score -> ordered level array as criteria", api_q["sev"]["criteria"] == ["tiny", "small", "moderate", "big", "huge"]
          and api_q["sev"]["type"] == "score" and api_q["sev"]["instructions"] == "how severe?")
    check("noul -> true/false criteria", api_q["cust"]["criteria"] == {"true": "touches a customer", "false": "internal only"})
    check("choice -> option:description criteria", api_q["own"]["criteria"] == {"a": "team A", "b": "team B"})
    # score with no levels falls back to (hi-lo+1) synthesized labels
    check("score criteria synthesized when no levels given",
          len(ts._to_api_questions([{"id": "s", "kind": "score", "scale": [1, 5], "prompt": "p"}])["s"]["criteria"]) == 5)
    # response parsing: API score is 0..(levels-1); internal score is lo + api_score
    resp = {"answers": {"sev": {"type": "score", "score": 3.0, "confidence": 0.9},
                        "cust": {"type": "noul", "noul": 0.8},
                        "own": {"type": "choice", "choice": "b", "probabilities": {"a": 0.3, "b": 0.7}}}}
    raw = ts._from_api_answers(scored, resp)
    check("API score 3 on a [1,5] scale -> internal 4", raw["sev"]["score"] == 4)
    check("noul passes through", raw["cust"]["noul"] == 0.8)
    check("choice maps 'choice' -> internal 'value'", raw["own"]["value"] == "b")
    # end-to-end: parsed raw is coerced into the declared types
    coerced = {q["id"]: ts._coerce(q, raw[q["id"]]) for q in scored}
    check("parsed + coerced score stays in scale", coerced["sev"]["score"] == 4)

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
