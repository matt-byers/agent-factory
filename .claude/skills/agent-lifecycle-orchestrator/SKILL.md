---
name: agent-lifecycle-orchestrator
description: Start, inspect, resume, and route the repository's first-build or continuous-improvement agent lifecycle. Use for initial setup, lifecycle status, selecting the next agent-creation skill, resuming an engineering receipt, or recovering after upstream artifacts change.
---

# Agent Lifecycle Orchestrator

Treat `agent-lifecycle/state.yaml` and validated artifacts as the durable source of truth. Do not infer progress from conversation history.

## Commands

Run the repository setup once before lifecycle setup:

```bash
scripts/agent-setup
```

Configure lifecycle providers and engineering-loop selection:

```bash
scripts/agent-lifecycle setup \
  --simulator-model <model> \
  --judge-model <model> \
  --evidence-mode <local|langfuse> \
  --engineering-loop <included|external>
```

Then use:

```bash
scripts/agent-lifecycle start first-build
scripts/agent-lifecycle start improvement
scripts/agent-lifecycle status
scripts/agent-lifecycle next
scripts/agent-lifecycle resume --receipt agent-lifecycle/receipts/<receipt>.json
```

## Workflow

1. Run `status` before acting and report its stage and exact `next` value.
2. Invoke the returned skill or complete the returned external action.
3. Run `next`; allow it to advance only after the current stage's artifacts validate.
4. When the included loop is selected, invoke `/agent-build-loop` with the active handoff. When an external loop is selected, provide that loop the same handoff and receipt contract.
5. At `awaiting_engineering`, run `scripts/engineering-handoff prepare --kind <build|improvement>` and pass that unchanged contract to the selected loop. Run the included loop immediately or pause while the selected external loop works.
6. Resume either engineering path with `resume --receipt` after validating its manifest-bound receipt. A failed or incomplete result retains its evidence at `agent-lifecycle/attempts/` without advancing.
7. If the receipt declares `architecture_changed`, invoke `/agent-architecture-planner reconcile` and advance only after its receipt-bound picture and decision evidence validates. Otherwise continue directly to baseline or held-in validation without rewriting architecture.
8. If `status` reports changed upstream artifacts, follow its rewound stage rather than continuing from stale downstream work.

Never edit lifecycle state by hand, skip a missing artifact, accept a failed or mismatched receipt, or expose held-out evidence before its gate.
