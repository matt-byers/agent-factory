---
name: agent-eval-designer
description: Design representative agent evaluation suites with deterministic graders, narrow qualitative rubrics, metrics, edge and adversarial cases, held-out coverage, and a generic simulated user. Use at the first-build eval-design stage or when revising eval coverage before implementation.
---

# Agent Eval Designer

Treat `agent-lifecycle/evals/suite.yaml` and its sealed held-out payloads as durable outputs. Do not run the target agent or diagnose failures in this skill.

## Workflow

1. Run `scripts/agent-lifecycle status` and continue only at `eval_design` or when explicitly revising eval coverage.
2. Read the complete files under `agent-lifecycle/agent-definition/`. Derive cases from stated users, risks, success outcomes, metrics, and commercial value without inventing requirements.
3. Use [assets/suite-template.yaml](assets/suite-template.yaml) and [assets/case-template.yaml](assets/case-template.yaml). Include smoke, capability, regression, edge, positive, negative, representative, adversarial, and held-out coverage.
4. Give every case a public opening, private user truth, progressive disclosure policy, stopping conditions, expected outcome and trajectory, deterministic invariants, narrow rubrics, tags, trials, and seeds.
5. Keep deterministic checks separate from qualitative judgments. Track deterministic, qualitative, and operational metrics. Prefer the smallest case set that covers materially different behavior.
6. Save the complete draft outside committed artifacts, then render and validate:

```bash
scripts/agent-eval-designer render --input <suite.json>
scripts/agent-eval-designer validate
```

7. Report the suite path and case counts by tag and split. Run `scripts/agent-lifecycle next` only after validation succeeds.

Never expose private truth, graders, expected outcomes, or sealed held-out payloads to the target agent. Do not open held-out payloads before the held-out lifecycle gate. Leave execution to `/eval-agent`.
