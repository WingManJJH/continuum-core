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

    print(f"\n{len(PASS)} passed, {len(FAIL)} failed")
    if FAIL:
        print("FAILED:", ", ".join(FAIL))
        sys.exit(1)


if __name__ == "__main__":
    main()
