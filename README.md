Agent Factory is a guided agent skillset that walks anyone through creating a working, valuable, self-improving AI agent. It centres on two core flows: defining the agent's goals, value, evals, architecture, and initial setup; then using evals and production traces drive continuous improvement.

## Principles

1. **Best-practice packages over custom infrastructure.** Agent building and evaluation lean on established packages — the LangSmith local runner, AgentEvals, OpenEvals, and Langfuse — rather than rolling custom implementations. See [Packages and evaluation infrastructure](#packages-and-evaluation-infrastructure) for details.
2. **Coding-harness agnostic.** The repository is designed to be cloned and is immediately compatible with both Claude Code and Codex. Skill and project-agent updates are kept in alignment across both harnesses through automated sync scripts and a staged pre-commit gate.
3. **Evals-led iteration.** Every agent is rooted in a clear user goal, and every improvement is tied to verifiable target outcomes or reproducible failure cases.

## Quickstart & setup

```bash
git clone <repository-url> agent-factory
cd agent-factory
direnv allow
claude --dangerously-skip-permissions "/onboard"
```

The final command starts a Claude Code session and invokes `/onboard`, which runs `scripts/agent-setup`, configures model-provider and optional Langfuse credentials one at a time, explains the two Agent Factory flows, and hands off to the first-build lifecycle. Codex users can open Codex and invoke `/onboard` instead. Credentials are entered through a hidden local terminal prompt and never pasted into chat.

`direnv allow` adds the repository `bin/` directory to the local command path, including the exact `testagent` command. Repository setup creates `.venv`, installs `requirements.txt`, copies `.env.example` to `.env` only when `.env` is absent, installs the pre-commit gate, and validates Claude/Codex adapters.

Eval result destinations and their optional credential setup are documented in [docs/references/eval-result-providers.md](docs/references/eval-result-providers.md).

## Setting up the agent

Agent Factory works in two phases:

1. **Initial goal setting:** capture the agent's context, goals, business case, and success criteria; design evals and a simulated user; plan the architecture; then implement to a measured baseline.
2. **Evals-led iteration:** run evals or promote production evidence, diagnose failures, apply evidence-linked improvements or eval repairs, and validate changes against held-in and held-out cases.

Agent Factory defines the user goal before the agent implementation. Each test case combines a simulated user—with their motivation, private context, questions, disclosure behavior, and desired outcome—with separate eval criteria describing what the target agent must achieve across the conversation.

```text
User goals and scenario
    ↓
Test case: simulated user + private context
    ↓
Evals: expected outcome + trajectory + graders
    ↓
Simulated user ↔ target agent conversation
    ↓
Grade → diagnose → improve → validate
    ↺ rerun and add the next scenario
```

Solved cases remain held-in regression coverage, while unseen variations stay sealed for held-out validation. The diagram below shows the first build and the complete improvement loop, including formal simulated-user evals, exploratory `testagent` probes, production evidence, engineering handoffs, and repeated validation.

```mermaid
flowchart TD
    subgraph L["/agent-lifecycle-orchestrator routes stages, validates artifacts, and resumes receipts"]
        direction TB
        subgraph F["First build"]
            direction TB
            ONBOARD["/onboard<br/>repository + credentials"] --> SETUP["lifecycle setup"]
            SETUP --> GOAL["/agent-goal-interview<br/>brief + commercial value model"]
            GOAL --> DESIGN["/agent-eval-designer<br/>cases + rubrics + simulated user"]
            DESIGN --> ARCH["/agent-architecture-planner<br/>architecture picture + build handoff"]
            ARCH --> BUILD{"Selected engineering loop"}
            BUILD --> MINI["/spec-plan → /agent-build-loop<br/>TDD plan + optional testagent probes"]
            BUILD --> EXTERNAL["External coding agent<br/>or preferred engineering loop"]
            MINI --> RECEIPT["Engineering receipt"]
            EXTERNAL --> RECEIPT
            RECEIPT --> RECONCILE["/agent-architecture-planner<br/>reconcile picture if architecture changed"]
            RECONCILE --> BASELINE["/eval-agent<br/>simulated user ↔ target agent<br/>baseline evaluation"]
            BASELINE --> OPERATIONAL["Agent baseline<br/>prompt, toolset"]
        end

        subgraph I["Continuous improvement"]
            direction TB
            IMPROVESTART{"Start from"}
            IMPROVESTART --> EVALRUN["/eval-agent<br/>run formal test cases"]
            IMPROVESTART --> PROD["/agent-production-evidence<br/>select production trace"]
            EVALRUN --> CONVERSATION["Simulated user ↔ target agent<br/>conversation + trajectory"]
            CONVERSATION --> EVIDENCE["Eval artifacts or promoted trace"]
            PROD --> EVIDENCE
            EVIDENCE --> REVIEW["/agent-behavior-review<br/>diagnose behavior and ownership"]
            REVIEW -.-> PROBE["testagent + conversation runner<br/>exploratory boundary probes"]
            PROBE -.-> REVIEW
            REVIEW --> IMPROVE["/agent-self-improvement<br/>generate learnings + bounded fixes"]
            IMPROVE -->|"eval, harness, or evidence repair"| EVALFIX["Apply eval/evidence fix"]
            EVALFIX --> EVALRUN
            IMPROVE -->|"agent harness or context change"| CHANGE["Improvement handoff"]
            CHANGE --> CHANGELOOP{"Selected engineering loop"}
            CHANGELOOP --> CHANGEBUILD["/spec-plan → /agent-build-loop<br/>or external loop"]
            CHANGEBUILD --> CHANGERECEIPT["Engineering receipt"]
            CHANGERECEIPT --> CHANGESYNC["/agent-architecture-planner<br/>reconcile if required"]
            CHANGESYNC --> HELDIN["/eval-agent<br/>held-in validation"]
            HELDIN --> HELDOUT["/eval-agent<br/>held-out validation"]
            HELDOUT --> LEARN["/eval-compound-learnings<br/>improve the eval loop"]
            LEARN --> AGAIN{"Run test cases again?"}
            AGAIN -->|"yes"| EVALRUN
            AGAIN -->|"no"| END(["End"])
        end

        OPERATIONAL ~~~ IMPROVESTART
    end
```

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
