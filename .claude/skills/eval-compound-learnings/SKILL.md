---
name: eval-compound-learnings
description: Compound evidence-supported improvements to the repository eval loop after an accepted or rejected target-agent improvement attempt. Use after held-in or held-out validation reaches a conclusive decision to update eval cases, simulated users, rubrics, evidence capture, providers, comparison gates, or eval operator guidance and return the lifecycle to operational.
---

# Eval Compound Learnings

Improve measurement quality after each conclusive improvement attempt. Keep this separate from target-agent implementation and engineering-process improvement.

## Workflow

1. Read the accepted or rejected held-in or held-out decision and its immutable source evidence.
2. Identify only evidence-supported weaknesses in offline eval cases, simulated-user behavior, rubrics, online evaluator mappings or calibration, evidence capture, provider workflow, comparison gates, or eval operator guidance.
3. Apply the smallest supported changes to those eval-loop surfaces. If the evidence supports no change, record a concise no-op reason.
4. Inspect every changed path. Reject target agent, surrounding application, `/agent-build-loop`, `/spec-plan`, and other engineering-loop changes.
5. Call `record_eval_loop_learning(root, improvements, no_op_reason=...)` from `agent_creation.eval_compound_learnings`. Give each improvement a lowercase hyphen-case `id`, an allowed `category`, a concise `summary`, one or more repository `path#anchor` evidence references, and the exact `changed_paths`.
6. Run the focused tests for each changed eval-loop surface and `.venv/bin/python -m pytest -q tests/test_eval_compound_learnings.py`.
7. Confirm the runtime records `agent-lifecycle/evidence/eval-loop-learning.yaml` and returns the lifecycle to `operational`.

Allowed categories are `eval_case`, `simulated_user`, `rubric`, `evidence`, `provider`, `comparison_gate`, and `operator_guidance`. Do not record a proposed change as completed: every changed path and evidence reference must exist, remain inside the repository, and match the digest captured by the runtime.

Route implementation-agent, TDD, review, commit, deployment, or build-loop lessons elsewhere. Never modify the target agent or engineering-loop skills through this skill.
