---
name: multi-council
description: "Run a decision through five advisors on five different models from five different labs, have them peer-review each other anonymously, and synthesize a divergence-first verdict. MANDATORY TRIGGERS: 'council this', 'ask the council', 'run the council', 'multi-council this', 'run the multi council', 'cross-model council', 'war room this', 'pressure-test this', 'stress-test this', 'debate this'. Also use when the user presents a high-stakes decision with real tradeoffs where a single vendor's blind spots would be invisible. Do NOT use for factual lookups, creation tasks, or decisions with one clear right answer."
---

# multi-council

Five advisors. Five different models. Five different labs. Claude chairs and never advises.

The point is decorrelation. Five sub-agents on one model share weights, priors, and blind
spots — whatever disagreement they produce was scripted by their prompts. Five models from
five labs disagree because they actually see the question differently.

## When to run it

Worth it when being wrong is expensive and the answer is genuinely uncertain. Not worth it
for lookups, creation tasks, or anything with one right answer. Each run takes a few minutes
and costs between half a cent and a dime.

## Step 1 — Frame the question

Read the user's question. Scan the workspace for context that would ground the advisors:
`CLAUDE.md`, `AGENTS.md`, a `memory/` directory, files the user referenced. Spend under 30
seconds.

Write ONE neutral framed question containing the core decision, relevant context, and what's
at stake. **Add no opinion and no steer.** If the question is too vague to frame, ask one
clarifying question, then proceed.

## Step 2 — Advise round

Pick a roster from `rosters.json` (default `reference`; use `zero_subscription` if the user
has no coding subscriptions). Build a jobs file where **every advisor gets the identical
prompt**:

```
You are an advisor on a council. Another advisor's answer will not be shown to you.

QUESTION:
<framed question>

Give your honest assessment. Commit to a position — do not hedge, do not present a balanced
survey of options, do not caveat your way to safety. If you think this is a mistake, say so
plainly. If you think it is obviously right, say that.

150-300 words. No preamble.
```

**Do not assign roles.** No Contrarian, no Expansionist. If advisors differed in both model
and role, nothing would distinguish model-driven disagreement from role-driven disagreement,
and you would report manufactured conflict as genuine uncertainty.

Write the jobs to a temp file in exactly this shape — the top-level `jobs` key is
required, and a bare array will fail:

```json
{
  "jobs": [
    {"seat": "gpt",      "transport": "codex",      "model": "gpt-5.6-luna",                   "prompt": "<advisor prompt>"},
    {"seat": "gemini",   "transport": "agy",        "model": "gemini-3.1-pro-high",            "prompt": "<advisor prompt>"},
    {"seat": "glm",      "transport": "claude_zai", "model": "glm-5.2",                        "prompt": "<advisor prompt>"},
    {"seat": "deepseek", "transport": "openrouter", "model": "deepseek/deepseek-v4-flash-0731", "prompt": "<advisor prompt>"},
    {"seat": "inkling",  "transport": "openrouter", "model": "thinkingmachines/inkling-small",  "prompt": "<advisor prompt>"}
  ]
}
```

`seat`, `transport`, `model`, and `prompt` are all required. `timeout_s` is optional and
defaults by transport. `seed` is optional too and applies to `openrouter` seats only — set
it when re-running a council so a changed answer traces to the changed question rather than
to sampling noise. Every advisor's `prompt` is identical in the advise round.

Then run:

```bash
python multi-council/scripts/dispatch.py --jobs <tmp>/advise.json
```

## Step 3 — Review round

Take the responses where `ok` is true. Assign them letters A–E **with the mapping shuffled**,
so position carries no information. Send every advisor this prompt:

```
The advisors below answered the question. Their responses are anonymized.

QUESTION:
<framed question>

RESPONSE A:
<text>

... (one block per responding advisor, lettered from A)

Answer three questions, referencing responses by letter:
1. Which response is strongest, and why?
2. Which has the biggest blind spot, and what is it missing?
3. What did ALL of them miss?

Under 200 words. Be direct.
```

Letter only the advisors that actually responded — never leave a placeholder for a seat that
failed.

Dispatch the same way. If fewer than three advisors responded in Step 2, **stop here** and
tell the user the council could not be seated — do not synthesize.

## Step 4 — Synthesize

You now hold the de-anonymized responses and all reviews. Write the verdict directly into
chat. No files, no HTML.

Five rules, and the first two are the reason this skill exists:

**Lead with divergence.** Where advisors disagreed is the highest-information part of the
run. It is the part that cannot be explained by shared training data.

**Treat unanimity as a flag, not as confidence.** These models share pretraining sources and
similar alignment pressure. Their errors are correlated, so agreement may be a shared blind
spot rather than a converged truth. Synthesis *promotes* correlated errors, because agreement
reads as confidence. When all five agree, say so — and say that it warrants a check for
shared priors rather than treating it as settled.

**Never count votes.** No tallies, no majorities. A 4–1 split is not 80% confidence. Side
with a lone dissenter when its reasoning is strongest, and say when you do.

**Flag responses that missed the question.** No script can catch this — a fluent answer to
the wrong question is indistinguishable from a correct one without reading it. If a response
does not engage the framed question, say so and exclude it from the verdict rather than
folding it in. The `agy` transport in particular can return a confident answer to the wrong
prompt with a success status.

**Name the empty seats.** If a model failed, report which and why. **Never write a response
for a seat that did not answer.**

Output:

```
## Council Verdict: <topic>

### Where the Council Diverged
### What Only One Advisor Saw
### Where the Council Agreed
### The Recommendation
### The One Thing to Do First
### Seats
```

## Setup

- `OPENROUTER_API_KEY` — required for any `openrouter` seat
- `ZAI_API_KEY` — required only for the `claude_zai` seat

If you swap in a different OpenRouter model, check that its `architecture.modality`
ends in `->text`. OpenRouter carries image, video, speech, embedding, and rerank models
alongside text ones, and a non-text seat produces a failed or garbage advisor. Filter on
modality, never on the model's name — `cogview-4` and `vidu-q1` have no "image" in their
names, while `inkling-small` reports `text+image+audio->text` and is a perfectly good
advisor because it *emits* text.
- `codex` seats need `codex login status` to report logged in
- `agy` seats need Antigravity installed and signed in
- Prompts are passed on stdin for `codex` and `claude_zai`, so they are not bound by
  Windows' ~8191-char command-line limit. The `agy` seat still passes its prompt in argv
  and is capped near 32,000 characters — a council over a very large document may lose
  that seat.

Check a roster without spending anything:
`python multi-council/scripts/dispatch.py --jobs <file> --dry-run`
