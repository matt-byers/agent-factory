# Agent Factory

Agent Factory gives anyone a structured starting point for building an AI agent with an evals-first approach. It turns an agent idea into a clear definition of user and commercial value, measurable success criteria, representative evals, a recommended architecture, and an implementation-ready plan. The aim is to ensure the agent is built and improved against evidence of actual value—not just whether its output looks plausible.

It is a CLI-first, skills-based workspace for Claude Code and Codex. The included skills guide the user through the complete agent lifecycle:

1. Define the user problem, agent goal, scope, trade-offs, and commercial value model.
2. Turn those goals into test cases, rubrics, held-out evals, and a simulated user before implementation.
3. Recommend an appropriate model call, workflow, agent, or multi-agent architecture using maintained agent-building best practices.
4. Produce a bounded engineering handoff and implement it through the included tests-first build loop, a preferred external engineering loop, or a standard coding agent.
5. Establish a measured baseline, then improve the agent using eval failures, exploratory `testagent` conversations, and production traces.

The result is a durable set of artifacts that explains what the agent should do, why it should exist, how it creates measurable value, what should be built, and how success will be judged. Those artifacts live alongside the target agent, allowing the lifecycle to resume from repository state instead of relying on chat history.

Agent Factory focuses only on the target agent harness and context: prompts, model and tool configuration, context management, workflows, agent state, skills, and subagents. It does not build the surrounding product, UI, database, authentication, infrastructure, or services that the agent uses.

## What it enables

- Start from an agent idea without needing an existing eval framework or agent-development process.
- Connect behavior metrics to user outcomes and unit economics such as time saved, revenue, cost, gross profit, or avoided loss.
- Design evals before implementation so architecture and engineering decisions are anchored to explicit success criteria.
- Test any target-agent runtime through a small language-agnostic protocol, locally or with Langfuse-backed evaluation and production evidence.
- Diagnose failures before changing the agent and validate candidate improvements against held-in and held-out cases.
- Use the included mini engineering loop or swap in any preferred coding workflow without changing the lifecycle artifacts.

## Clone setup

```bash
git clone <repository-url> agent-factory
cd agent-factory
direnv allow
scripts/agent-setup
```

`direnv allow` adds the repository `bin/` directory to the local command path, including the exact `testagent` command. Setup creates `.venv`, installs `requirements.txt`, copies `.env.example` to `.env` only when `.env` is absent, installs the repository pre-commit gate, and validates Claude/Codex adapters. Add one model-provider key for each selected simulator or judge directly to `.env`. Add Langfuse credentials only when selecting the Langfuse evidence destination. Never put credentials in chat.

Eval result destinations and their optional credential setup are documented in [docs/references/eval-result-providers.md](docs/references/eval-result-providers.md).

## Packages and evaluation infrastructure

Agent Factory keeps local execution separate from remote observability:

| Component | What it does | Account or credentials |
|---|---|---|
| LangSmith Python package | Runs local offline evals through `evaluate`/`aevaluate` with `upload_results=False`. It is an internal runner dependency, not a hosted destination. | None |
| AgentEvals | Scores agent trajectories, including expected tool-use sequences. | Uses the selected judge model when required |
| OpenEvals | Supplies LLM-as-judge evaluators and multi-turn simulated-user execution. | Uses the selected simulator or judge model |
| Langfuse | Stores remote traces, datasets, experiments, scores, source links, and production evidence used by the improvement loop. | `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, `LANGFUSE_BASE_URL` |
| pytest | Tests lifecycle state, artifact integrity, provider adapters, eval gates, skills, and the engineering loop. | None |

LangChain and LangGraph are referenced by the architecture-planning guidance and may be recommended for a target agent when appropriate. Agent Factory does not require the target agent to use either framework. They may also appear in the virtual environment as dependencies of the evaluation packages.

The model-provider variables—`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `GOOGLE_API_KEY`—are optional individually. Configure only the providers selected for the simulator and judge roles. LangSmith environment variables are intentionally unsupported because Agent Factory never uploads to LangSmith.

## Repository infrastructure

| Component | What it does |
|---|---|
| Python and `.venv` | Run the lifecycle library, deterministic helpers, eval adapters, and tests in an isolated repository environment. |
| `scripts/` and `bin/` | Provide the CLI experience, including setup, lifecycle, eval, build-loop, harness checks, and the exact `testagent` command. `direnv` adds `bin/` to the path. |
| JSONL target protocol | Lets the eval runner and `testagent` drive an agent implemented in any language without coupling Agent Factory to its runtime or application API. |
| `.claude/`, `.agents/`, and `.codex/` | Keep one repository-owned set of skills available to Claude Code and Codex, with paired project-agent definitions rendered and checked for parity. |
| `agent-lifecycle/` | Stores durable briefs, value models, architecture, eval definitions, evidence, handoffs, receipts, and attempt state so workflows can resume from artifacts rather than chat history. |
| Git pre-commit hook | Rejects staged drift between Claude and Codex skill/agent adapters. It does not replace the test suite. |

The repository uses the Python standard library for its core lifecycle and artifact logic. The complete third-party runtime dependency list is intentionally small and lives in `requirements.txt`: `langsmith`, `agentevals`, `openevals`, `langfuse`, and `pytest`.

## Repository shape

```text
agent-factory/
├── README.md
├── CLAUDE.md
├── AGENTS.md -> CLAUDE.md
├── .env.example
├── requirements.txt
├── bin/
├── .claude/
│   ├── skills/
│   │   ├── agent-lifecycle-orchestrator/
│   │   ├── agent-goal-interview/
│   │   ├── agent-eval-designer/
│   │   ├── agent-architecture-planner/
│   │   ├── spec-plan/
│   │   ├── agent-build-loop/
│   │   ├── human-verify/
│   │   ├── eval-agent/
│   │   ├── agent-behavior-review/
│   │   ├── agent-production-evidence/
│   │   ├── agent-self-improvement/
│   │   └── eval-compound-learnings/
│   └── agents/
│       ├── testagent-conversation-runner.md
│       ├── live-transcript-reviewer.md
│       ├── finding-fragment-writer.md
│       └── final-spec-compiler.md
├── .agents/skills -> ../.claude/skills
├── .codex/agents/
│   ├── testagent-conversation-runner.toml
│   ├── live-transcript-reviewer.toml
│   ├── finding-fragment-writer.toml
│   └── final-spec-compiler.toml
├── .githooks/pre-commit
├── docs/references/
├── scripts/
├── src/agent_creation/
├── tests/
└── agent-lifecycle/
    ├── setup.yaml
    ├── state.yaml
    ├── agent-definition/
    ├── architecture/
    ├── evals/
    ├── evidence/
    ├── handoffs/
    ├── receipts/
    └── attempts/
```

## Lifecycle

```mermaid
flowchart TD
    subgraph L["/agent-lifecycle-orchestrator routes stages, validates artifacts, and resumes receipts"]
        direction TB
        subgraph F["First build"]
            direction TB
            SETUP["setup"] --> GOAL["/agent-goal-interview<br/>brief + commercial value model"]
            GOAL --> DESIGN["/agent-eval-designer<br/>cases + rubrics + simulated user"]
            DESIGN --> ARCH["/agent-architecture-planner<br/>architecture picture + build handoff"]
            ARCH --> BUILD{"Selected engineering loop"}
            BUILD --> MINI["/spec-plan → /agent-build-loop<br/>TDD plan + optional testagent probes"]
            BUILD --> EXTERNAL["External coding agent<br/>or preferred engineering loop"]
            MINI --> RECEIPT["Engineering receipt"]
            EXTERNAL --> RECEIPT
            RECEIPT --> RECONCILE["/agent-architecture-planner<br/>reconcile picture if architecture changed"]
            RECONCILE --> BASELINE["/eval-agent<br/>baseline evaluation"]
            BASELINE --> OPERATIONAL["Agent baseline<br/>prompt, toolset"]
        end

        subgraph I["Continuous improvement"]
            direction TB
            IMPROVESTART{"Start from"}
            IMPROVESTART --> EVALRUN["/eval-agent<br/>run test suite with user agent"]
            IMPROVESTART --> PROD["/agent-production-evidence<br/>select production trace"]
            EVALRUN --> EVIDENCE["Eval artifacts or promoted trace"]
            PROD --> EVIDENCE
            EVIDENCE --> REVIEW["/agent-behavior-review<br/>diagnose with optional testagent probes"]
            REVIEW --> IMPROVE["/agent-self-improvement<br/>generate learnings + bounded fixes"]
            IMPROVE -->|"eval, harness, or evidence repair"| EVALFIX["Apply eval/evidence fix"]
            EVALFIX --> FIXRERUN["/eval-agent<br/>rerun repaired test cases with user agent"]
            FIXRERUN --> FIXRETURN(["Return to eval artifacts<br/>and diagnosis"])
            IMPROVE -->|"agent harness or context change"| CHANGE["Improvement handoff"]
            CHANGE --> CHANGELOOP{"Selected engineering loop"}
            CHANGELOOP --> CHANGEBUILD["/spec-plan → /agent-build-loop<br/>or external loop"]
            CHANGEBUILD --> CHANGERECEIPT["Engineering receipt"]
            CHANGERECEIPT --> CHANGESYNC["/agent-architecture-planner<br/>reconcile if required"]
            CHANGESYNC --> HELDIN["/eval-agent<br/>held-in validation"]
            HELDIN --> HELDOUT["/eval-agent<br/>held-out validation"]
            HELDOUT --> LEARN["/eval-compound-learnings<br/>improve the eval loop"]
            LEARN --> AGAIN{"Run test cases again?"}
            AGAIN -->|"yes"| RERUN["/eval-agent<br/>run test suite with user agent"]
            RERUN --> REPEAT(["Repeat from Start"])
            AGAIN -->|"no"| END(["End"])
        end

        OPERATIONAL ~~~ IMPROVESTART
    end
```

## Harness checks

```bash
scripts/agent-config/sync_agent.py --from claude live-transcript-reviewer
scripts/agent-config/verify_agent_config.py
scripts/test-agent-config.sh
```

The staged pre-commit gate runs only when harness files are staged and rejects broken links, malformed skills, missing role pairs, or stale role renderings.
