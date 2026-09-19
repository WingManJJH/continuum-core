"""
System One seam — TypeSafe AI's Jev, for fast *typed decisions* (not prose).

Sibling to llm.py. Where the LLM seam is System Two (planning, narrative) this is
System One: send some state + a list of typed questions, get one typed answer each
in a single parallel pass. Three question kinds, matching Jev's primitives:

  - choice : pick one of `options`      -> {"value", "confidence", "probabilities"}
  - score  : a point on a [lo, hi] scale -> {"score", "confidence"}
  - noul   : is a statement true?        -> {"noul"}  (0..1 probability)

Jev cannot emit an invalid *type*; we ALSO coerce/validate every answer on our side
(clamp scores, reject options that aren't in the list) so a bad transport or a wire
hiccup can never inject an out-of-type value into the governed model. As with the
LLM seam: no key + no injected transport => it refuses (callers fall back or skip);
a `transport(state, questions) -> dict` runs the whole path with no key and no
network for tests.

Env:
  CONTINUUM_TYPESAFE_API_KEY
  CONTINUUM_TYPESAFE_MODEL     (default below)
  CONTINUUM_TYPESAFE_BASE_URL  (default: TypeSafe decide endpoint)

Jev outputs are probabilistic classifications — advisory signal, not authority.
They must land through the governed, audited write path with a human or a
deterministic rule owning the final call; never treat a typed answer as truth.
"""
from __future__ import annotations

import json
import os

API_KEY_ENV = "CONTINUUM_TYPESAFE_API_KEY"
MODEL_ENV = "CONTINUUM_TYPESAFE_MODEL"
BASE_URL_ENV = "CONTINUUM_TYPESAFE_BASE_URL"
DEFAULT_MODEL = "jev-1"
DEFAULT_BASE_URL = "https://api.typesafe.ai/v1/decide"
KINDS = ("choice", "score", "noul")


def api_key() -> str | None:
    return os.environ.get(API_KEY_ENV)


def model() -> str:
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL)


def available(transport=None) -> bool:
    """True when Jev can be reached — an injected transport, or a real key."""
    return bool(transport) or bool(api_key())


class QuestionError(ValueError):
    """A malformed typed question — caught before anything is sent."""


def _validate(questions: list[dict]) -> None:
    if not isinstance(questions, list) or not questions:
        raise QuestionError("questions must be a non-empty list")
    seen = set()
    for q in questions:
        qid, kind = q.get("id"), q.get("kind")
        if not qid or qid in seen:
            raise QuestionError(f"each question needs a unique id (got {qid!r})")
        seen.add(qid)
        if kind not in KINDS:
            raise QuestionError(f"{qid}: kind must be one of {KINDS}")
        if kind == "choice" and not (isinstance(q.get("options"), list) and q["options"]):
            raise QuestionError(f"{qid}: a choice needs a non-empty options list")
        if kind == "score":
            sc = q.get("scale")
            if not (isinstance(sc, (list, tuple)) and len(sc) == 2 and sc[0] < sc[1]):
                raise QuestionError(f"{qid}: a score needs scale [lo, hi] with lo < hi")


def decide(state, questions: list[dict], transport=None) -> dict:
    """Answer every typed question about `state`. Returns {question_id: answer}, each
    answer coerced to its declared type. `state` is any JSON-able context."""
    _validate(questions)
    if transport is None and not api_key():
        raise RuntimeError("no Jev access — set CONTINUUM_TYPESAFE_API_KEY")
    raw = transport(state, questions) if transport else _call_api(state, questions)
    if not isinstance(raw, dict):
        raise ValueError("Jev transport must return a dict of {question_id: answer}")
    return {q["id"]: _coerce(q, raw.get(q["id"])) for q in questions}


def _num(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def _coerce(q: dict, ans):
    """Force an answer into the question's declared type — the governed model never
    sees an out-of-type value even if the model/transport misbehaves."""
    kind = q["kind"]
    d = ans if isinstance(ans, dict) else {}
    if kind == "noul":
        v = _num(d.get("noul", ans))
        return {"noul": min(1.0, max(0.0, v))}
    if kind == "score":
        lo, hi = q["scale"]
        v = _num(d.get("score", ans), lo)
        return {"score": min(hi, max(lo, v)), "confidence": min(1.0, max(0.0, _num(d.get("confidence", 1.0), 1.0)))}
    # choice
    opts = q["options"]
    val = d.get("value", ans)
    probs = d.get("probabilities") if isinstance(d.get("probabilities"), dict) else None
    if val not in opts:                       # reject anything outside the declared list
        val = max(probs, key=probs.get) if probs else opts[0]
        if val not in opts:
            val = opts[0]
    return {"value": val, "confidence": min(1.0, max(0.0, _num(d.get("confidence", 1.0), 1.0))),
            "probabilities": probs}


def _call_api(state, questions: list[dict]) -> dict:
    """POST state + typed questions to Jev over stdlib urllib (no new dependency).
    The wire shape follows the documented choice/score/noul primitives; adjust the
    endpoint/field names here if TypeSafe's API differs from the defaults."""
    import urllib.request as _rq
    body = json.dumps({"model": model(), "state": state, "questions": questions}).encode()
    req = _rq.Request(os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL), data=body, headers={
        "content-type": "application/json", "authorization": "Bearer " + api_key()})
    with _rq.urlopen(req, timeout=30) as resp:  # nosec - fixed TypeSafe endpoint
        data = json.loads(resp.read())
    # accept {"answers": {id: ...}} or a bare {id: ...}
    return data.get("answers", data) if isinstance(data, dict) else {}
