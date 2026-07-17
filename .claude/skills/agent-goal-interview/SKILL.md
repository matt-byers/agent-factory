---
name: agent-goal-interview
description: Interview a user to define an agent's purpose, users, problem, scope, risks, accuracy/latency/cost trade-offs, observable outcomes, and measurable success metrics. Use when starting or revisiting the first-build goal-definition stage.
---

# Agent Goal Interview

Read [references/interview-guide.md](references/interview-guide.md) before interviewing. Treat the files under `agent-lifecycle/agent-definition/` as the durable output; do not rely on conversation history.

## Workflow

1. Run `scripts/agent-lifecycle status` and continue only at `goal_definition` or when explicitly revising the goal.
2. Ask focused questions in small groups. Restate uncertain answers and resolve contradictions rather than filling gaps yourself.
3. Capture a structured interview object matching the guide. If required users, outcomes, or metrics remain absent, report `needs_follow_up` and ask the precise missing questions.
4. Save the structured response to a temporary JSON file outside committed artifacts.
5. Model commercial value and unit economics using the guide. Save the structured model to a temporary JSON file, then render and validate all artifacts:

```bash
scripts/agent-goal-interview render --input <interview.json>
scripts/agent-goal-interview validate
scripts/agent-business-value calculate --input <business-model.json>
scripts/agent-business-value validate
```

6. Report the four artifact paths and any unresolved assumptions. Run `scripts/agent-lifecycle next` only after both validators succeed.

Never invent a baseline, target, source, owner, failure cost, or commercial outcome. Keep surrounding application code, databases, UI, infrastructure, and deployment outside the editable agent surface.
