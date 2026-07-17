---
name: agent-architecture-planner
description: Select and maintain the simplest evidence-supported runtime architecture for a target AI agent. Use after agent goals, business value, and eval cases are complete, or after implementation changes require the target agent architecture picture to be reconciled.
---

# Agent Architecture Planner

Create or maintain the target agent's architecture decision and its one Mermaid visual source of truth.

## Required inputs

Read these repository artifacts before recommending a shape:

- `agent-lifecycle/agent-definition/project-brief.md`
- `agent-lifecycle/agent-definition/success-metrics.yaml`
- `agent-lifecycle/agent-definition/business-value-model.yaml`
- `agent-lifecycle/evals/suite.yaml`
- `docs/references/agent-building-best-practices.md`

Consult the current LangChain and LangGraph documentation for the framework interfaces relevant to the candidate shape. Treat the generated best-practices reference and its source markers as the durable architecture-selection contract.

Stop if any required lifecycle artifact is pending, invalid, or contradicts another input. Ask for the owning artifact to be repaired instead of inventing missing evidence.

## Select the architecture

Choose the simplest shape supported by the inputs:

1. Use `model_call` for one bounded inference without tools or adaptive control.
2. Use `workflow` when model steps and routing are known in advance.
3. Use `agent` when one coherent domain requires dynamic tool choice or recovery.
4. Use `multi_agent` only when named eval cases demonstrate a single-agent limit across separable domains and independent directions.

Compare the choice against the stated accuracy, latency, cost, commercial-value, and eval constraints. Do not add complexity merely as an evolution path.

## Produce and validate

Create a temporary JSON planning request matching the deterministic contract in `src/agent_creation/architecture_planner.py`. Include the requested shape, model steps, adaptive-execution need, tools, specialist domains, independent directions, acceptance eval IDs, single-agent-limit eval IDs, and external dependencies.

Run:

```bash
scripts/agent-architecture-planner plan --input <request.json>
scripts/agent-architecture-planner validate
```

When lifecycle status returns `architecture_reconciliation`, inspect only the implemented files named by the accepted receipt, prepare the same deterministic architecture request from the implemented runtime, and run:

```bash
scripts/agent-architecture-planner reconcile \
  --receipt <accepted-receipt.json> \
  --input <request.json>
scripts/agent-lifecycle next
```

The reconciliation is receipt- and implementation-bound. Do not reconcile an unchanged, stale, failed, tampered, or surrounding-application receipt.

Maintain only:

- `agent-lifecycle/architecture/agent-architecture.md`
- `agent-lifecycle/architecture/decisions.md`

Keep one Mermaid diagram in `agent-architecture.md`. It must show only the target runtime agent, its internal model/workflow/agent components, tools, and runtime context. Exclude test agents, evals, graders, lifecycle skills, engineering loops, production-evidence collection, and surrounding application architecture. Record databases, APIs, user interfaces, and other application systems as external dependencies in prose, not editable diagram components or recommendations.

Link each important choice to the goal, metric, value-model, eval, and best-practice evidence that supports it. After implementation changes, reconcile the same diagram and decisions file. For renamed agents or tools, use ordinary repository search and replace; do not create rename maps or parallel projections.

## Create the engineering handoff

After the architecture recommendation is approved, prepare the engineering handoff request. Give every recommendation its requirement or observed evidence, likely cause or design need, proposed change, source-linked rationale, expected user and business effect, and acceptance eval IDs. Declare only exact editable files under the target agent surfaces; do not use directories, globs, databases, UI paths, or other surrounding-application files.

Include focused tests, the full deterministic suite, acceptance evals, and review gates, then run:

```bash
scripts/engineering-handoff create --input <handoff-request.json>
```

Do not replace an existing handoff identifier. Pass the generated manifest, implementation specification, acceptance gates, and bound receipt template to the selected engineering loop.
