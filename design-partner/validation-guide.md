# Design-Partner Validation Guide — the "editable guardrail" hypothesis

**Status:** Ready to run · **Date:** 2026-08-25
**Source:** Core Model §13 step 4 — fold this document into the design-partner conversations already planned for pricing/ICP validation.
**Scope:** This does **not** re-run pricing or ICP discovery. It rides along on those calls to test one narrow thing, then gets out of the way.

---

## 1. The one hypothesis under test

> **H:** "Guardrails a process owner can edit without an engineering ticket" is the feature that makes Continuum land — a capability a buyer recognizes as *theirs to control*, not a technical detail they nod past.

Two ways this can fail, and both are worth knowing:
- **Fail-A (wrong feature):** owners don't actually want to hold this — they expect engineering/IT to own agent permissions, and "you can edit it yourself" reads as *work being pushed onto them*, or as *unsafe*.
- **Fail-B (right feature, wrong words):** owners want exactly this, but "guardrail" / "policy" / "without an engineering ticket" doesn't connect — it needs a different frame (control, approval, boundary, "what the AI is allowed to do") to land.

Fail-A changes the roadmap. Fail-B changes the pitch. We must be able to tell them apart before we build the Phase-2 governance UI around this promise.

## 2. Why it's worth a dedicated test

The whole architecture bets on it. "Guardrails are data, not code" (§01) and "a process owner changes agent behavior by editing a record instead of filing an engineering ticket" (§04) is the load-bearing differentiator vs. every incumbent (Camunda/GBTEC/Mavim model processes; none put an *editable agent-permission layer* in the process owner's hands). If the owner doesn't want that control or can't recognize it, the differentiator is invisible and we're a nicer-looking process repository.

## 3. Who to test it with (recruit from the existing pool)

The person on the call who should react to this is the **process owner / operations lead** — the ISO 9001 §4.4 "single accountable owner", not the CTO and not the AI champion. If your pricing/ICP call is with a buyer or a technical lead, ask them near the end: *"Who would actually own what the AI is allowed to do in this process day-to-day?"* — and if it's someone else, that answer is itself a finding (it tells you whether ownership sits where the architecture assumes).

Ideal: 5–8 conversations across the ICP already being validated, each including at least one true process/operations owner.

## 4. The test — run it in three moves

Keep it to ~12 minutes at the end of an existing call. Do **not** lead with our words for it; the point is to hear theirs first.

### Move 1 — Elicit the problem in their language (unprimed, ~4 min)
Ask, and shut up:
- "When you put an AI agent on a step in one of your processes today, who decides what it's allowed to do on its own vs. what needs a person? How does that decision get made and changed?"
- "The last time you wanted to change what an automated step could do — tighten it after something went wrong, or loosen it because it was too cautious — what did that take?"

**Listen for the spontaneous frame.** Write down the *exact nouns* they use: "permissions"? "rules"? "approvals"? "controls"? "what it can touch"? "sign-off"? That vocabulary is the Fail-B answer if our words don't match theirs.

### Move 2 — Show the capability, not the label (concrete demo, ~4 min)
Walk them through the actual edit, using the prototype (see §5). Narrate it in **neutral** terms the first time:
> "Here's one step — verifying a KYC document. This is the boundary the AI runs inside: what it can do on its own, what it's never allowed to do, when it has to pull in a human, and which data it can see. Right now, high-risk cases go to a human lead. Say you decide that's too cautious — watch."

Then change `escalate_if` from `risk_score > 0.7` to `> 0.95`, save, and re-run the same case (`risk_score: 0.9`) so it now returns **allow** instead of **escalate** — with no code, no deploy, a new version stamped.

Ask:
- "Who in your org should be able to make that change?"
- "What would it take to trust that this is the *only* way the AI can act — that there's no back door around it?" (probes the §11 bypass concern, which is often the real blocker to adoption)

### Move 3 — Framing A/B (~4 min)
Now test the words directly. Present the **same capability** under three one-line frames and ask which one they'd forward to their boss, and why:

| # | Frame |
|---|---|
| **F1** | "Guardrails your process owners can edit without an engineering ticket." |
| **F2** | "You set the boundaries for what the AI can do — and change them yourself, instantly, without waiting on IT." |
| **F3** | "Every automated step has an approval policy you own: what's allowed, what escalates to a person, what's off-limits." |

Force a rank. The winner (and the reasons) is the Fail-B signal — if F1, our current language is fine; if F2/F3 consistently beat it, we reframe.

## 5. The demo asset

Use the working prototype, not slides — it exists precisely so this is show-not-tell:

```bash
cd continuum-core/mcp_server
python3 scenario.py          # the agent loop: allow / escalate / deny, live
```

To demo the **edit**: open `../data/seed.json`, change `gr.CO.3.2.7` → `escalate_if` from `"risk_score > 0.7"` to `"risk_score > 0.95"`, bump its `version` to 4, and re-run `scenario.py` — step 3 (`risk_score: 0.9`) flips from **escalate** to **allow**, and the logged action now cites `v4`. That version-stamped, no-deploy change *is* the pitch, performed live.

> Optional, higher-fidelity: stand up a 2-field web form over the Guardrail Policy object so the owner drags `escalate_if` themselves. Only build this if early calls show the *concept* lands and the friction question becomes "can a non-technical owner really do it" — don't build UI to test a concept the CLI demo can carry.

## 6. Signals & decision criteria

Tally across calls:

| Signal | Reading |
|---|---|
| Owner lights up at Move 2, wants to hold the control themselves | **H supported** — build the Phase-2 governance UI on this promise |
| Owner recognizes the capability but a **different frame** (F2/F3) consistently wins | **Fail-B** — keep the feature, change the pitch to the winning frame; re-test the new words on the next 2 calls |
| Owner wants engineering/IT to own it, or reads self-edit as burden/risk | **Fail-A** — the differentiator is mis-targeted; revisit who the guardrail UI is *for* before building it |
| The first question is "how do I know the AI can't go around this?" | Bypass-prevention (§11) is a **gating concern**, not a detail — it must be in the pitch, not buried in architecture |
| Owner has no current way to do this at all and didn't know they'd want it | Latent need — strong, but confirm they'll *change* one live in the demo, not just admire it |

**Kill/continue gate:** if ≥4 of the first ~6 owner conversations land as Fail-A, stop and revisit the ownership assumption before Phase 2 spends UI budget on an editor nobody wants to own.

## 7. How this folds into the pricing/ICP calls

- It's the **last ~12 minutes**, after pricing/ICP, so it never distorts those answers.
- The Move-1 vocabulary doubles as **positioning research** for the pricing/ICP work — the nouns owners use for "control over the AI" are the nouns the pricing page and the ICP messaging should use too.
- Log every call in the shared tracker with three fields: *spontaneous frame (their words)*, *A/B winner (F1/F2/F3)*, *Fail-A / Fail-B / Supported*. Those three columns are the entire deliverable back to the team — a decision, not a transcript.

## 8. One-page leave-behind (send after the call)

> **Continuum — the part your competitors don't have**
> Modeling your processes is table stakes. The difference: for every step you hand to an AI, *you* hold the boundary it runs inside — what it can do alone, what it must bring to a person, what it can never do, and what data it can see. Change that boundary yourself, the moment you need to, and every change is versioned for your next audit. No engineering ticket. No deploy. No waiting on IT.
> *Ask us to show you a boundary change go live in 30 seconds.*
