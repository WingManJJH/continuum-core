# Continuum — Executive Walkthrough

*A one-page brief for a design-partner conversation. Pair it with the live demo
(three running apps) and the [validation guide](validation-guide.md).*

---

## The thesis, in one line

**Your processes become the guardrail layer every AI action runs against** — and the
person who owns the process can change what the AI is allowed to do, without an
engineering ticket.

## The problem you already have

You're putting AI agents into real work. The question no tool answers today: *what is
each agent allowed to do on its own, who decided that, and can you prove it to an
auditor?* Process tools map how work should run; none of them put an **editable
agent-permission layer in the process owner's hands**. So agent permissions live in
code, change by deploy, and leave no trail — exactly the wrong place for something a
compliance team has to stand behind.

## What Continuum does — three claims

1. **Governed autonomy.** Every step an agent runs is bound to a *guardrail*: what it
   may do alone, what it must escalate to a human, what it can never do, and which data
   it may touch. The guardrail is a **gate the action passes through**, not advice — the
   agent literally cannot act outside it.
2. **Owned by the business, not engineering.** A process owner edits that guardrail in a
   web page. The change is versioned and **live for agents on the next call — no deploy**.
3. **Provable.** Every edit and every agent action lands on a **tamper-evident audit
   trail** (hash-chained), mapped to ISO 9001 §7.5. And because strategy, process, and
   agent all live in one model, a leader can trace an objective down to the agent action
   executing it — and back.

## See it in ~4 minutes (the live demo)

1. **Open the process canvas.** Click a step — say KYC verification. See the boundary
   the AI runs inside: allowed actions, escalation condition, data scope. Change *"escalate
   high-risk cases to a human"* and **Save** — a new version, no code, no deploy.
2. **Watch it bite.** The same case the agent used to auto-approve now routes to a person
   — the edit is live, no restart.
3. **See it roll up.** The leadership dashboard shows the change: which steps run under an
   agent, what the agent did, and whether it moved the KPI it was meant to.
4. **Try to cover it up.** Edit the audit log by hand — the chain flags **tampering**. The
   record is defensible.

## What we want to learn from you

We're testing one thing: whether *"guardrails a process owner can edit without an
engineering ticket"* is the capability that lands — or needs to be said differently.
Specifically:

- **Who** in your org should own what an AI is allowed to do on a given process — day to
  day, without filing a ticket?
- In **your words**, what would you call this — permissions? approvals? controls?
  guardrails? (We want your vocabulary, not ours.)
- What would it take to trust that this is the **only** way the AI can act — no back door?

## Honest status (so you know exactly what you're seeing)

This is a **working prototype**, not a slide. The model, the editable guardrails, the
enforcement gate, the tamper-evident audit trail, and the strategy-to-execution dashboard
all run and are tested end-to-end. Two things need *your* environment, not more building:
the **live connectors** (Notion / Teams / Slack / Outlook / Gmail) that feed real activity
in are gated on your OAuth, and guardrail **coverage starts low on purpose** — only a
reviewed guardrail counts, so the number tells the truth about what's been signed off.

*Ask us to show a guardrail change go live in 30 seconds.*
