---
name: agent-build-loop
description: Run the repository's concise interchangeable engineering loop against an accepted build plan, exact agent allowlist, and immutable handoff, then produce a commit-bound engineering receipt.
---

# Agent Build Loop

Use this included loop only when lifecycle setup selects it. An external engineering loop may replace it if that loop consumes the same immutable handoff and returns the same receipt contract.

Never change surrounding application code. Never weaken a test or gate to make it pass.

## Ordered contract

1. **Plan acceptance** — verify the approved handoff, accepted `build-plan.md`, dependencies, and exact allowlist before editing.
2. **RED** — write the planned test first, run its focused command, and retain the real non-zero result for the intended reason.
3. **Implementation** — make the smallest change within the unit's exact files.
4. **Focused GREEN** — run the accepted focused command until it passes.
5. **Self-verification** — run the planned deterministic checks and smoke tests. Route only irreducibly manual checks through `/human-verify`.
6. **testagent** — when enabled by the plan, run the exact `testagent` command with bounded probes and retain its transcript. It supplements deterministic checks.
7. **Review** — compare the diff with the accepted plan, repository instructions, architecture, and named best practices. Resolve all blocking and high findings.
8. **Full suite** — after every unit passes review, run one full suite exactly once.
9. **Commit** — stage the accepted files explicitly, verify the exact allowlist, and commit with explicit paths while preserving unrelated worktree changes.
10. **Receipt** — write the manifest-, plan-, test-, smoke-, review-, and commit-linked engineering receipt for lifecycle resume.

Record evidence through `scripts/agent-build-loop record`. Complete the final boundary through:

```bash
scripts/agent-build-loop commit \
  --attempt <attempt-id> \
  --message "agent: <accepted change>" \
  --architecture-changed <true|false>
```

Do not add execution waves, child-agent fan-out, rigor tiers, stack-specific UX gates, retrospectives, deployment, or pull-request creation.
