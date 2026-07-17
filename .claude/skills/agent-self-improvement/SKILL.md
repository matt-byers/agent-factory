---
name: agent-self-improvement
description: Coordinate evidence-driven target-agent improvement from eval or production evidence through diagnosis, direct evidence repair or an immutable engineering handoff, and held-in/held-out validation. Use when iterating on an existing agent after a failure, regression, or production trace.
---

# Agent Self Improvement

Coordinate the loop; delegate evidence collection to `/eval-agent` or `/agent-production-evidence` and qualitative diagnosis to `/agent-behavior-review`. Read `docs/references/agent-building-best-practices.md` before accepting an agent recommendation.

1. Select one diagnostic source: a native eval run, promoted production trace, or bounded exploratory `testagent` transcript.
2. Invoke `/agent-behavior-review` and require deterministic ownership plus reproducibility evidence.
3. For eval-definition, simulated-user, target-data, harness, provider, or evidence ownership, repair that repository surface, rerun only affected test cases, and return the new artifacts directly to diagnosis. Do not invoke an engineering loop or agent held-in/held-out gates.
4. For surrounding-application ownership, retain evidence, name the database/service/API/auth/infrastructure/UI/UX owner, and stop without an agent recommendation.
5. For inconclusive or non-reproducible behavior, gather better evidence or stop. Do not create a handoff.
6. Only for an approved, reproducible target-agent failure, create the immutable evidence- and best-practice-linked improvement handoff with exact agent-surface paths and acceptance evals.
7. Route that handoff through the selected engineering loop from repository setup. The included `/agent-build-loop` is interchangeable with an external loop.
8. Resume from its receipt, reconcile the architecture picture only if architecture changed, then run held-in before releasing held-out validation.
9. Accept, reject, or mark the candidate inconclusive against the baseline; return failed evidence to diagnosis and retain the final decision artifacts.

Exploratory `testagent` runs help reproduce behavior during diagnosis and may give quick implementation feedback, but they never replace deterministic tests or acceptance evals.
