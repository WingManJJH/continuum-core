# Default Guardrail Policy Template

**Status:** ✅ SIGNED OFF for Phase 1 (fractional QMS/ISO advisor, 2026-08-26) · **Version:** 1
**Source:** Core Model §04 (guardrail fields), §11 (risk: over-restrictive guardrails kill the value proposition), §13 step 3.
**Reviewer of record:** fractional QMS/ISO advisor (`role.qms.iso_advisor`) — reviewed and signed off at design time, per §13, *before* a customer audit rather than retrofitted for one. Sign-off recorded in [`default-guardrail-policy.json`](default-guardrail-policy.json) `review`.
**Machine-readable form:** [`default-guardrail-policy.json`](default-guardrail-policy.json) (validates against `../schema/guardrail-policy.schema.json`).

---

## The doctrine this template encodes

> Design the default policy template to start **permissive within a narrow, well-scoped action set** and tighten based on observed incidents, not the reverse. — Core Model §11

A guardrail so conservative that every action escalates is a guardrail nobody wants their agents bound by; the humans meant to be a safety valve become a bottleneck and start rubber-stamping (§11, escalation fatigue). So the default is deliberately **generous inside a fence**, not locked-down:

- **Permissive** — the allow-list covers the actions that make an agent useful on almost any process: read, summarize, classify, annotate, ask for more information, flag for a human, draft (but not send) a response.
- **Narrow & well-scoped** — none of those can mutate external state, move money, make a final decision, or touch data the task didn't explicitly grant. Everything irreversible or outward-facing is on the *forbidden* list by name.
- **Tightened by evidence, not by fear** — the change path is "an incident happened → add the specific action to `forbidden_actions` / lower `escalate_if`", captured as a new policy version with the incident cited in `review.note`. We do not start maximally locked and loosen on request; that path trains owners to over-restrict and never revisit.

## Field-by-field

| Field | Default value | Why this default |
|---|---|---|
| `allowed_actions` | `read_record, summarize, classify, add_note, request_information, flag_for_review, draft_response` | The largest set of actions that are useful on an arbitrary process **and** reversible / non-final. `draft_response` is allowed; **sending** it is not (`send_external` is forbidden) — the split between "prepare" and "commit" is where the fence sits. |
| `forbidden_actions` | `approve, reject_final, disburse_funds, modify_permissions, delete_record, send_external, close_case` | Kept as an **explicit** list, not "everything not allowed", so an ISO 9001 audit sees what was *deliberately* excluded (§04). Each is either irreversible, outward-facing, or a final decision — the three classes an unattended agent should never own by default. |
| `escalate_if` | `risk_score > 0.7 or confidence < 0.6` | Two triggers: high risk on the case, or low agent confidence in its own output. Set *loose enough that routine work does not escalate* (the anti-fatigue calibration) and tightened per process from the escalation acceptance/rejection rate (§12). |
| `data_scope` | `[]` (empty → copied from the task at instantiation) | Least privilege **by construction**: a fresh policy grants access to *nothing*, and stamping it onto a task copies exactly that task's declared `data_scope` — never "the whole customer record" (§04). |
| `rate_limit` | `60 actions / 60 s` | Contains a looping or runaway agent automatically (§04). A per-process default; high-volume automated processes raise it explicitly with an owner's sign-off. |
| `escalation_path` | `role.process_owner` | A **role**, not a person, so coverage survives turnover (§04). Resolves to the owning process's `owner_role` at instantiation. |
| `audit_requirement` | `inputs_outputs` | The middle tier: enough to reconstruct what the agent did without full reasoning capture. High-stakes processes raise it to `full_capture`; pure-read steps may drop to `timestamp_outcome`. |
| `version` | `1` | Every edit is a new version; an in-flight agent pins the version it read and cites it when logging (§04). |

## `escalate_if` expression grammar

Evaluated by the Enforcement Point against the `facts` an agent supplies with `check_guardrail`. Deliberately small and side-effect-free (implemented as a whitelisted-AST evaluator in `continuum_core._safe_eval` — no arbitrary code):

- **Operands:** field names (looked up in `facts`; an unknown field is `None`), numbers, booleans.
- **Comparisons:** `>` `>=` `<` `<=` `==` `!=`
- **Boolean:** `and` `or` `not`, parentheses for grouping.
- **Safety:** any comparison against a missing fact is `False`, never an error — a missing signal cannot silently satisfy an escalation *or* silently bypass one; combine with a required-fields check on the calling side for hard gates.

Examples:
```
risk_score > 0.7 or confidence < 0.6            # the default
transaction_amount > 10000                       # financial threshold
customer_tier == "enterprise" and confidence < 0.8
not sanctions_clear                              # a boolean fact
```

## ISO 9001 mapping (advisor review notes)

The point of reviewing the default with the QMS/ISO advisor *now* is that an auditor later reads the **same object** the agent's guardrail check reads — there is no parallel compliance artifact (§10). Clause-by-clause:

| ISO 9001 clause | How the default satisfies it |
|---|---|
| **§4.4** process approach — determine controls, risks, responsibilities | Controls = the allow/forbid lists; risk trigger = `escalate_if`; responsibility = `escalation_path` (a single accountable role). The guardrail *is* the documented operational control for the process's agent actions, linked from the Risk & Control register entry it enforces. |
| **§6.1** actions to address risks | The default's forbidden-list + `escalate_if` are the preventive control for the "confidently-wrong autonomous action" risk. A process's `RiskControl.guardrail_ref` points at the very policy that mitigates it — risk register and enforcement are one link, not two documents. |
| **§7.5** documented information / control | `version` + event-sourced writes give version, author, timestamp, and review note on every policy change automatically — document control as a side effect of storage, not a separate workflow. `review.reviewed_by` / `reviewed_at` / `note` carry the approval trail. |
| **§8.5.1** controlled production/service provision | An agent may act unattended only within a reviewed, versioned control; anything outside it escalates to a competent human. The default makes "controlled" the only mode an agent can operate in. |
| **§9.1 / §10** monitoring & improvement | Escalation accept/reject rate per guardrail (§12) is the monitoring signal; tightening the policy from observed incidents, each as a new version citing the incident, is the §10 corrective-action loop, implemented. |

**Advisor's standing caveats (to hold the line on):**
1. *Never* add an action to `allowed_actions` that commits external state without also deciding whether it needs a matching `escalate_if` — "allowed" and "unconditional" are not the same.
2. A process handling personal data must narrow `data_scope` to the specific fields the task needs *before* going live — the empty default is safe, a lazily-broad instantiation is not.
3. Every tightening after an incident must cite the incident in `review.note`. An audit trail of *why* a control changed is worth as much as the change.

## How the default is applied

At the moment a task first gets an agent binding, the system stamps a **copy** of `gr.DEFAULT` onto the task's owning process (or the task, for an override), then:
1. copies the task's `data_scope` into the policy's `data_scope`,
2. resolves `role.process_owner` to the concrete `owner_role`,
3. sets `attaches_to` to the real process/task ref,
4. bumps to `version: 1` under the owner's name and leaves the advisor's review note attached.

From there it is the process owner's to edit — **without an engineering ticket** — which is the exact capability Deliverable 4 puts in front of design partners.
