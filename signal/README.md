# Signal Layer & Conformance Check — Phase 3

The "Check" in Plan-Do-Check-Act (Core Model §06 Figure 4). The signal layer observes
reality — external activity + every agent's execution log — and the Conformance Check
compares it against the documented model, surfacing where they diverge.

## Drift types detected

| Type | Severity | Source | Meaning |
|---|---|---|---|
| `stale_guardrail` | HIGH | agent log | an agent action cited a policy version older than current — the §06 early-warning: correct behavior against a stale guardrail is a compliance risk before anyone notices |
| `off_model_action` | HIGH | agent log | an agent successfully did an action its policy doesn't list |
| `coverage_gap` | LOW | signal | observed activity uses an action neither allowed nor forbidden by the guardrail |
| `undocumented_step` | MEDIUM | signal | observed a task id not in the model |
| `shadow_process` | MEDIUM | signal | observed activity in a process not in the model |

**Per §06, drift is surfaced, never auto-applied.** Every finding carries a proposed
resolution and `requires_human_review: true`; the Conformance Check never writes to the
model — a human closes the loop (the "Act"). A test asserts this non-mutation invariant.

## Live connectors need OAuth (flagged, not faked)

`connectors.py` declares `NotionConnector` / `OutlookConnector` with their required OAuth
scopes; in this build they **raise a clear error** rather than pretend to connect (auth is
unavailable here). `FileConnector` stands in with the fixtures below so the conformance
engine — the part that must be correct — is exercised end to end. Swap the live connectors
in once authorized; the `SignalConnector.read()` interface is unchanged.

## Run

```bash
python3 signal/conformance.py          # human report over the fixtures
python3 signal/conformance.py --json   # machine-readable
python3 signal/test_conformance.py     # 8 assertions (incl. "never mutates the model")
```

## Files

- `connectors.py` — `SignalConnector` interface, `FileConnector` (stand-in), Notion/Outlook OAuth stubs.
- `conformance.py` — the Conformance Check engine + report.
- `signals.sample.jsonl` — fixture external activity (one conformant + one of each signal-side drift).
- `agent_events.sample.jsonl` — fixture agent-log events (stale, off-model, and one conformant).
- `test_conformance.py` — asserts each drift type is found and the model is never mutated.
