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


# Phase 4 — full enterprise connection. Same OAuth-gated pattern.
class TeamsConnector(_OAuthConnector):
    name = "teams"
    scopes = ["Chat.Read", "ChannelMessage.Read.All"]


class SlackConnector(_OAuthConnector):
    name = "slack"
    scopes = ["channels:history", "groups:history"]


class GmailConnector(_OAuthConnector):
    name = "gmail"
    scopes = ["gmail.readonly"]


# Sequenced by sensitivity (per the business plan): least-sensitive first, so the
# signal layer earns trust before it reaches a mailbox. This is the order to enable
# connectors in as OAuth becomes available.
SENSITIVITY_ORDER = ["notion", "teams", "slack", "outlook", "gmail"]

LIVE_CONNECTORS = {
    "notion": NotionConnector, "outlook": OutlookConnector,
    "teams": TeamsConnector, "slack": SlackConnector, "gmail": GmailConnector,
}


def default_sources() -> list[SignalConnector]:
    """Live connectors (Notion/Teams/Slack/Outlook/Gmail) all require OAuth, which
    is unavailable in this build, so the file connector stands in for the whole set.
    As each connector is authorized — in SENSITIVITY_ORDER — swap it in here; the
    SignalConnector.read() interface is unchanged, so nothing downstream changes."""
    return [FileConnector()]
