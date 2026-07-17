---
name: agent-production-evidence
description: Query production Langfuse traces, select and locally redact evidence, deduplicate it, and promote it into the agent improvement lifecycle. Use when starting diagnosis from production behavior or running the credentialed provider smoke.
---

# Agent Production Evidence

Collect evidence for the target agent only. Do not diagnose it, change the agent, create provider experiments, or mutate surrounding application systems.

## Query

Invoke the maintained host `/langfuse` skill when available; otherwise use the native Langfuse traces SDK/API. Apply narrow project, time, tag, status, user, or metadata filters and a bounded page limit.

Retain the provider trace identifier and direct source link. Keep raw provider payloads in memory only and pass selected traces through `agent_creation.production_evidence` before writing local artifacts.

## Promote

Select one exact trace with the provider-native get operation. Redact secret-shaped keys, assignments, and bearer tokens locally, then call `promote_evidence` with either:

- `diagnostic` to write `agent-lifecycle/evidence/selected-evidence.yaml` for `/agent-behavior-review`.
- `eval` to write one candidate under `agent-lifecycle/evals/candidates/` for `/agent-eval-designer` to review and incorporate.

Use the production evidence index to deduplicate repeated promotion of the same provider trace and destination. Do not insert a production trace directly into a held-out suite.

## Smoke

Use recording clients for the default offline smoke. With user-supplied sandbox credentials, create or identify one explicitly temporary trace, query it, promote it, verify the redacted artifact and source link, then clean up only that temporary trace and any temporary local promotion.

Credentialed Langfuse smoke is **Pending** until the user supplies sandbox credentials and account access. Record only redacted command output, the trace identifier/link, promoted artifact path, and cleanup confirmation. Never place credentials in command arguments, chat, or artifacts.

## Cleanup

Delete only an explicit temporary trace identifier through `cleanup_langfuse_trace`. Remove a local promoted artifact through `cleanup_promotion`, which verifies its fingerprint before deletion. Never delete production traces gathered for diagnosis or broad provider projects, datasets, or experiments.

Provider failures are inconclusive evidence. Preserve the redacted operation error and route provider or data problems to eval/evidence repair rather than treating them as target-agent failures.
