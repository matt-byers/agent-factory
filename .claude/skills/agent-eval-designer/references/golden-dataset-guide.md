# Golden Dataset Guide

The eval suite is a golden dataset: a curated set of task specifications that
defines what correct behavior looks like, not a pile of transcripts. Store the
spec; regenerate the conversation each run. Because a spec is decoupled from any
single run, the same case re-runs cleanly across model and prompt versions for
regression testing.

See `docs/references/agent-building-best-practices.md` (Evaluation and
observability) for the harness-level view this guide specializes.

## A task specification, not a transcript

Each case is a pending test case. The suite stores the fixed inputs and expected
results; the target agent produces the dynamic fields (actual output, tools
called) at eval time. A transcript is raw ore, not the deliverable — mine it for
a spec, then throw the wording away.

Every case captures, at the level this harness exposes:

- **Opening and world assumptions** — the public `initial_user_message`, plus any
  seeded state or account context the case presupposes, written into the persona
  and private truth.
- **Simulated-user brief** — a fixed goal, a persona, and the facts the user
  holds, disclosed progressively through `reveal_on` triggers.
- **Expected outcome** — the end state, not the wording. "Your booking is
  confirmed" is prose; the outcome is whether the effect the agent claims is real
  and grounded in tool results.
- **Expected trajectory (loosely)** — required and forbidden tools, and ordering
  only when a single order is genuinely correct.
- **Policy adherence** — where a policy governs the flow, score adherence
  separately from task success. An agent that resolves the request by violating
  policy is a partial failure, not a pass.

## Grade the outcome, then the path

Checking that the agent followed one exact sequence of tool calls is too rigid;
agents regularly find valid approaches you did not anticipate, and brittle path
checks reject good solutions. Prefer grading what the agent produced over the
path it took.

- Lead with deterministic **outcome and invariant** checks (required side effect
  present, forbidden action absent, answer grounded in tool results).
- Use **trajectory** checks for tool choice, arguments, forbidden tools, and
  stopping behavior. Leave `ordered_tools` empty unless one ordering is the only
  correct one.
- Use **narrow rubrics** for qualities that need judgment (resolution clearly
  explained, grounded in retrieved evidence), one criterion each.

## Make the simulated user difficult

LLM user simulators drift toward being overly cooperative and stylistically
homogeneous, which inflates measured success. Counter it deliberately, drawing
difficult behaviors from real interactions:

- Write personas that are vague, impatient, distracted, or change their mind
  mid-flow — not just clear and compliant.
- Withhold information until asked precisely: narrow `reveal_on` triggers force
  the agent to elicit facts rather than receive them freely.
- Vary who volunteers what: some users over-share irrelevant detail, others give
  the minimum.

## Balance should-do against should-not

One-sided suites create one-sided optimization. For every behavior, test both the
case where it should occur and the case where it should not. Include cases where
the correct action is to **refuse, escalate to a human, or decline** — and grade
that the agent does so, and separately that it does not refuse legitimate
requests. This is what the `positive` and `negative` coverage tags are for.

## Prove each case is solvable

Before finalizing a case, confirm a known-good response exists that passes every
grader. If no reasonable response can pass, the graders are misconfigured, not the
agent. The quality bar: two domain reviewers reading the spec would independently
reach the same pass/fail verdict. If they would not, tighten the spec.

## Source cases from real failures

- Cluster real transcripts by intent; each cluster becomes a slice of coverage.
- Draft the spec from a transcript with an LLM, then have a human verify it.
- Anonymize before storing; never keep raw customer data in a committed case.
- 20-50 tasks drawn from real failures is a strong start — early on each change
  has a large effect size, so small samples suffice.

## Capability, regression, and reliability

- **Capability** cases start at a low pass rate — a hill to climb. **Regression**
  cases sit near 100% and guard against backsliding. A capability case that
  saturates graduates into the regression set.
- Practice eval-driven development: write the case that defines a planned
  capability before the agent can pass it, then iterate.
- Runs are stochastic. Use multiple `trials` with distinct `seeds`; for
  customer-facing behavior that users expect every time, judge on all trials
  passing (pass^k), not an average.
- Feed production failures back in continuously so the suite stays
  representative, and keep held-out cases sealed until the held-out gate.
