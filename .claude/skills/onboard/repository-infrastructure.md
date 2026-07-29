# Repository infrastructure

Component overview for orienting a new user during onboarding.

| Component | What it does |
|---|---|
| Python and `.venv` | Run the lifecycle library, deterministic helpers, eval adapters, and tests in an isolated repository environment. |
| `scripts/` and `bin/` | Provide the CLI experience, including setup, lifecycle, offline evals, online-eval planning and review selection, build-loop, harness checks, and the exact `testagent` command. `direnv` adds `bin/` to the path. |
| JSONL target protocol | Lets the eval runner and `testagent` drive an agent implemented in any language without coupling Agent Factory to its runtime or application API. |
| `.claude/`, `.agents/`, and `.codex/` | Keep one repository-owned set of skills available to Claude Code and Codex, with paired project-agent definitions rendered and checked for parity. |
| `agent-lifecycle/` | Stores durable briefs, value models, architecture, eval definitions, evidence, handoffs, receipts, and attempt state so workflows can resume from artifacts rather than chat history. |
| Git pre-commit hook | Rejects staged drift between Claude and Codex skill/agent adapters. It does not replace the test suite. |

The repository uses the Python standard library for its core lifecycle and artifact logic. The complete third-party runtime dependency list is intentionally small and lives in `requirements.txt`: `langsmith`, `agentevals`, `openevals`, `langfuse`, and `pytest`.
