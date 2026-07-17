---
name: human-verify
description: Record rare irreducibly manual smoke-test evidence in the owning accepted agent build plan. Use only for human judgment, consent, physical feedback, or user-controlled external setup.
---

# Human Verify

Use this only when the accepted `build-plan.md` classifies a smoke test as manual and states why automation cannot observe it.

The owning `agent-lifecycle/attempts/<attempt-id>/build-plan.md` is the only durable status and evidence source. Do not create a separate checklist or verification report.

## Procedure

1. Show one concrete scenario, the minimal human action, and the expected observation.
2. Ask for the result and specific evidence.
3. Record exactly one terminal status: `Passed`, `Failed`, or `Blocked`.
4. Include the ISO date and concise evidence in the owning plan.
5. Treat `Failed`, `Blocked`, or `Pending` as a build-loop blocker.

Record the result through:

```bash
scripts/agent-build-loop human-verify \
  --attempt <attempt-id> \
  --unit <unit-id> \
  --smoke <smoke-id> \
  --status <Passed|Failed|Blocked> \
  --date <YYYY-MM-DD> \
  --evidence <evidence>
```

If an agent can observe the result through terminal output, files, logs, traces, screenshots, or deterministic commands, return it to automated self-verification instead.
