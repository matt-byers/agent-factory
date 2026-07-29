---
name: agent-eval-designer
description: Design representative agent evaluation suites with deterministic graders, narrow qualitative rubrics, metrics, edge and adversarial cases, held-out coverage, and a generic simulated user. Use at the first-build eval-design stage or when revising eval coverage before implementation.
---

# Agent Eval Designer

Treat `agent-lifecycle/evals/suite.yaml` and its sealed held-out payloads as durable outputs. Do not run the target agent or diagnose failures in this skill.

The suite is a golden dataset: a set of task specifications that defines what correct looks like, not a pile of transcripts. Store the spec; the conversation is regenerated each run. Read [references/golden-dataset-guide.md](references/golden-dataset-guide.md) before drafting, and `docs/references/agent-building-best-practices.md` (Evaluation and observability) for the harness-level view.

## Workflow

1. Run `scripts/agent-lifecycle status` and continue only at `eval_design` or when explicitly revising eval coverage.
2. Read the complete files under `agent-lifecycle/agent-definition/`. Derive cases from stated users, risks, success outcomes, metrics, and commercial value without inventing requirements. Where real or promoted transcripts exist, cluster them by intent with the deterministic tool below and draft cases from actual failures rather than imagined ones — one representative case per intent, and watch for a single intent crowding out the rest:

   ```bash
   scripts/agent-eval-designer cluster --input <items.json>   # list of strings or {id, text}
   scripts/agent-eval-designer cluster --suite <suite.json>   # cluster an existing suite's openings
   ```
3. Use [assets/suite-template.yaml](assets/suite-template.yaml) and [assets/case-template.yaml](assets/case-template.yaml). Include smoke, capability, regression, edge, positive, negative, representative, adversarial, and held-out coverage.
4. Give every case a public opening, private user truth, progressive disclosure policy, stopping conditions, expected outcome and trajectory, deterministic invariants, narrow rubrics, tags, trials, and seeds.
5. Design the case around these disciplines:
   - **Grade the outcome, then the path.** Lead with deterministic end-state and invariant checks; keep `ordered_tools` empty unless a single ordering is the only correct one. Do not demand one exact tool sequence when several are valid.
   - **Make the simulated user difficult.** Encode vague, impatient, or mind-changing behavior in the persona and withhold facts behind narrow `reveal_on` triggers, so the agent must elicit information rather than receive it freely. Generic cooperative users inflate success.
   - **Balance should-do against should-not.** For each behavior, cover both where it should occur (`positive`) and where the correct action is to refuse or escalate (`negative`). Score policy adherence separately from task success.
   - **Prove solvability.** Confirm a known-good response would pass every grader, and that two reviewers reading the spec would reach the same pass/fail verdict.
   - **Mark expert validation.** Every case carries a `validation` block. New cases default to `{"status": "pending"}`; a case only becomes a confirmed golden scenario when a human expert reviews the expected result and sets `{"status": "validated", "reviewer": "...", "reviewed_on": "YYYY-MM-DD"}`. A missing block reads as pending, so nothing is ever validated by accident. Track coverage with `scripts/agent-eval-designer report`, which lists the still-pending case ids.
6. Keep deterministic checks separate from qualitative judgments. Track deterministic, qualitative, and operational metrics. Prefer the smallest case set that covers materially different behavior. Split capability cases (a hill to climb) from regression cases (near 100%, guarding against backsliding), and use multiple trials with distinct seeds where model variance can change the conclusion.
7. Save the complete draft outside committed artifacts, then render and validate:

```bash
scripts/agent-eval-designer render --input <suite.json>
scripts/agent-eval-designer validate
```

8. Report the suite path and case counts by tag and split. Run `scripts/agent-lifecycle next` only after validation succeeds, then hand off the resulting `online_eval_design` stage to `/agent-online-eval-planner`.

Never expose private truth, graders, expected outcomes, or sealed held-out payloads to the target agent. Do not open held-out payloads before the held-out lifecycle gate. Leave execution to `/eval-agent`.
