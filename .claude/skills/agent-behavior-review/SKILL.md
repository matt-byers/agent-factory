---
name: agent-behavior-review
description: Diagnose target-agent eval artifacts, testagent transcripts, or promoted production evidence; assign deterministic failure ownership; and produce evidence-grounded improvement recommendations. Use when agent behavior fails, appears unreliable, or needs exploratory boundary testing before deciding whether to repair evidence or change the agent.
---

# Agent Behavior Review

Diagnose observable behavior before recommending changes. Read `docs/references/agent-building-best-practices.md` and cite the relevant section in every target-agent recommendation.

## Evidence

Accept native eval artifacts, promoted `agent-lifecycle/evidence/selected-evidence.yaml`, or a rich `testagent` transcript. Run:

```bash
python3 .claude/skills/agent-behavior-review/scripts/analyze_transcript.py <transcript>
```

Inspect cited messages, tool calls/results, state, errors, outcome, termination, metrics, and source links directly. Do not infer hidden reasoning or diagnose from a summary alone.

## Exploratory probes

Use the exact `testagent` command to test competing causal hypotheses and nearby behavior boundaries. Run at most three probes and four turns per probe. Change one relevant condition between probes, retain each transcript, and label it exploratory rather than an acceptance gate. Stop when the failure is reproduced, refuted, inconclusive, or would require surrounding-application changes.

Use `agent:testagent-conversation-runner` to execute a probe. For a growing transcript, use `agent:live-transcript-reviewer`; send supported candidates one at a time to `agent:finding-fragment-writer`; let only `agent:final-spec-compiler` write the final review.

## Ownership

Assign exactly one structured owner before proposing a change:

- `target_agent`: prompt, context, tool contract, workflow, model configuration, state, memory, middleware, skill, or target-runtime subagent behavior.
- `eval_definition`, `simulated_user`, `target_data`, or `harness`: repair the owning eval surface and rerun affected cases directly back to diagnosis.
- `provider` or bad evidence: repair evidence collection and return directly to diagnosis.
- `surrounding_application`: database, application service, API, authentication, infrastructure, UI, or UX owner outside this repository’s agent surface.
- `inconclusive`: collect better evidence; do not recommend implementation.

Only a reproducible `target_agent` failure may proceed to an engineering handoff. Never use agent held-in or held-out gates for an eval/evidence repair because the target agent did not change.

## Recommendation

For a reproducible target-agent failure, identify the evidence, causal mechanism, smallest exact agent-owned editable paths, rejected alternatives, best-practice rationale, expected user and business effect, affected held-in evals, and protected held-out coverage. Prefer deterministic tools, contracts, state, and routing over prompt patches when they make the desired behavior reliable. Keep external dependencies unchanged.

For externally owned failures, retain the evidence and name the owner. Emit no editable agent path or implementation recommendation.
