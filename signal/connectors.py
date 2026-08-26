"""
Signal Layer connectors — Phase 3 (Core Model §06, §09 Phase 3).

The signal layer feeds the Conformance Check: it observes real work (from
Teams/Slack/Notion/Outlook, sequenced by sensitivity per the business plan) plus
every agent's execution log, and hands normalized activity events to
conformance.py to compare against the documented model.

Normalized signal event:
    {ts, source, process, task?, action, actor}

LIVE CONNECTOR STATUS: the Notion and Outlook connectors require OAuth, which is
not available in this build (see the MCP auth notice). They are declared here
with the exact scope they will need, and raise a clear error rather than pretend
to connect. FileConnector stands in for them with hand-built fixtures so the
Conformance Check — the part that has to be correct — is exercised end to end.
"""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))


class SignalConnector:
    """Interface every source implements. read() returns normalized events."""
    name = "base"

    def read(self) -> list[dict]:
        raise NotImplementedError


class FileConnector(SignalConnector):
    """Reads normalized signal events from a JSONL fixture — the stand-in for a
    live source until connector OAuth is available."""
    name = "file"

    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(HERE, "signals.sample.jsonl")

    def read(self) -> list[dict]:
        if not os.path.exists(self.path):
            return []
        with open(self.path) as f:
            return [json.loads(x) for x in f if x.strip()]


class _OAuthConnector(SignalConnector):
    scopes: list[str] = []

    def read(self) -> list[dict]:
        raise RuntimeError(
            f"{self.name} connector requires OAuth (scopes: {', '.join(self.scopes)}), "
            f"which is unavailable in this environment. Authorize the connector in an "
            f"interactive session, then this connector replaces FileConnector unchanged."
        )


class NotionConnector(_OAuthConnector):
    name = "notion"
    scopes = ["read_content"]


class OutlookConnector(_OAuthConnector):
    name = "outlook"
    scopes = ["Mail.Read", "Calendars.Read"]


def default_sources() -> list[SignalConnector]:
    """Phase-3 sequencing: Notion/Outlook first (per §09). They need auth, so the
    file connector stands in; swap them in once authorized."""
    return [FileConnector()]
