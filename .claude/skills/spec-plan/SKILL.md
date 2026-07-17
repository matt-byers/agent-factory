---
name: spec-plan
description: Create and explicitly accept a concise, self-contained tests-first build plan from an approved engineering handoff. Use before the included agent build loop implements a first build or improvement.
---

# Spec Plan

Turn the approved engineering handoff into the smallest executable plan that satisfies its recommendations and acceptance gates.

## Inputs

Read:

- the approved engineering handoff and immutable manifest;
- repository instructions;
- the architecture, goal, eval, and best-practice sources named by the handoff;
- the exact editable-path allowlist.

Do not plan surrounding application, database, UI, UX, deployment, or product changes. Stop if required work falls outside the exact agent-surface allowlist.

## Plan contract

Create `agent-lifecycle/attempts/<attempt-id>/build-plan.md` through:

```bash
scripts/agent-build-loop create-plan \
  --attempt <attempt-id> \
  --manifest <manifest-path> \
  --input <plan-request.json>
```

The plan must contain:

- every functional and non-functional requirement from the approved handoff;
- self-contained units in dependency order;
- exact files and requirement mappings for each unit;
- named architecture and agent-building best-practice sources;
- a test file, focused command, and intended RED reason before implementation;
- the bounded implementation and focused GREEN command;
- deterministic self-verification;
- observable smoke tests classified as automated or genuinely manual;
- an explicit optional `testagent` choice with bounded probes;
- review sources and one full-suite command after all units.

Keep context inside the unit that needs it. Do not add planning diaries, review ledgers, waves, fan-out, rigor tiers, stack-specific gates, retrospectives, deployment, or pull-request work.

## Acceptance

Present the complete plan for explicit acceptance. Do not edit agent files first.

After approval, bind acceptance to the plan content:

```bash
scripts/agent-build-loop accept-plan --attempt <attempt-id>
```

Any non-evidence edit invalidates acceptance and requires a new plan.
