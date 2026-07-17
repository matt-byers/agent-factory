# Self-Improving Agent Template

This repository creates, evaluates, and improves an agent harness and its context. Work through repository-owned skills from a terminal. Do not add a UI or modify the surrounding application.

## Setup

Run `direnv allow` and `scripts/agent-setup` after cloning. Direnv exposes repository commands from `bin/`; setup creates the local Python environment, preserves or creates `.env`, installs the repository pre-commit gate, and validates Claude/Codex discovery. Put credentials directly in `.env`; never paste secret values into chat or committed artifacts.

## Shared harness ownership

| Capability | Source of truth | Runtime adapter |
|---|---|---|
| Manual | `CLAUDE.md` | `AGENTS.md` symlink |
| Skills | `.claude/skills/` | `.agents/skills` symlink |
| Project agents | `.claude/agents/**/*.md` and `.codex/agents/*.toml` | `scripts/agent-config/sync_agent.py` |

Use `agent:<name>` when repository skills dispatch a project role. Synchronize an edited role explicitly:

```bash
scripts/agent-config/sync_agent.py --from claude path/to/role
scripts/agent-config/sync_agent.py --from codex path/to/role
```

Run `scripts/test-agent-config.sh` after changing manuals, skills, project agents, synchronization, or commit-gate behavior. Install or repair the staged gate with `scripts/agent-config/install_git_hooks.sh`.
