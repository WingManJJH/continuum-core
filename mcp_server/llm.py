"""
Shared LLM seam — one place that turns a model on when a key is present.

Both the Ask-the-Agent planner and the standards advisor use this so they wire to
the *same* env var and behave identically: with no key they refuse (their
deterministic engine stands in); with a key they call the model over stdlib
`urllib` (no extra dependency). A `transport` callable can be injected for tests so
the full path runs with no key and no network.

Env:
  CONTINUUM_LLM_API_KEY   (falls back to ANTHROPIC_API_KEY)
  CONTINUUM_LLM_MODEL     (default below)
  CONTINUUM_LLM_BASE_URL  (default: Anthropic Messages API)
"""
from __future__ import annotations

import json
import os
import re

API_KEY_ENV = "CONTINUUM_LLM_API_KEY"
MODEL_ENV = "CONTINUUM_LLM_MODEL"
BASE_URL_ENV = "CONTINUUM_LLM_BASE_URL"
DEFAULT_MODEL = "claude-opus-4-8"
DEFAULT_BASE_URL = "https://api.anthropic.com/v1/messages"


def api_key() -> str | None:
    return os.environ.get(API_KEY_ENV) or os.environ.get("ANTHROPIC_API_KEY")


def model() -> str:
    return os.environ.get(MODEL_ENV, DEFAULT_MODEL)


def available(transport=None) -> bool:
    """True when a model can be reached — an injected transport, or a real key."""
    return bool(transport) or bool(api_key())


def call_model(system: str, user: str, transport=None, max_tokens: int = 800) -> str:
    """Return the model's raw text. `transport(system, user) -> str` overrides the
    network call (used in tests). Raises RuntimeError when no key and no transport."""
    if transport:
        return transport(system, user)
    key = api_key()
    if not key:
        raise RuntimeError(
            "no model access — set CONTINUUM_LLM_API_KEY (or ANTHROPIC_API_KEY)")
    import urllib.request as _rq
    body = json.dumps({
        "model": model(), "max_tokens": max_tokens, "system": system,
        "messages": [{"role": "user", "content": user}],
    }).encode()
    req = _rq.Request(os.environ.get(BASE_URL_ENV, DEFAULT_BASE_URL), data=body, headers={
        "content-type": "application/json", "x-api-key": key,
        "anthropic-version": "2023-06-01"})
    with _rq.urlopen(req, timeout=30) as resp:  # nosec - fixed Anthropic endpoint
        data = json.loads(resp.read())
    return "".join(p.get("text", "") for p in data.get("content", []) if p.get("type") == "text")


def extract_json(raw: str):
    """Pull the JSON object or array out of a model reply (tolerates code fences)."""
    s = (raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", s.strip())
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        pass
    starts = [i for i in (s.find("{"), s.find("[")) if i >= 0]
    end = max(s.rfind("}"), s.rfind("]"))
    if not starts or end <= min(starts):
        raise ValueError("no JSON object or array in model reply")
    return json.loads(s[min(starts):end + 1])
