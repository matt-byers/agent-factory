# Agent Factory

Agent Factory is a guided skillset for building, evaluating, and improving LLM-based agents. It provides a disciplined path from product problem to an agent harness with measurable behavior—not a generic prompt template or an agent framework.

The central idea is simple: treat an agent as a product with an executable specification. Define the user outcome, express representative interactions as eval cases, implement the smallest architecture that can satisfy them, and use failures as evidence for the next change.

## Quickstart

Clone the repository and open it in Claude Code or Codex:

```bash
git clone <repository-url> agent-factory
cd agent-factory
```

Start the guided setup and lifecycle:

```text
/onboard
```

`/onboard` prepares the local environment, configures the providers you need, explains the first-build and improvement flows, and hands off to the lifecycle orchestrator. The repository then routes the work through the relevant skills; you do not need to choose the whole process up front.

## The mental model

An LLM solution is a system, not a model call. Its behavior comes from the interaction of the product objective, instructions and context, model, tools, control flow, and the user conversation. A change to any one of these can help one case while breaking another. Evals make those trade-offs visible.

Agent Factory organizes the work into five layers:

1. **Product specification** — identify the user, their job to be done, the agent's boundaries, the value of success, and unacceptable outcomes.
2. **Evaluation design** — turn the specification into realistic conversations and observable criteria. This is the executable product spec.
3. **Agent architecture** — select the context, tools, model roles, state, and control flow required to meet the evals. Prefer the simplest architecture that explains the requirements.
4. **Implementation and baseline** — build the harness, run the suite, and establish what the first version actually does.
5. **Evidence-led iteration** — turn eval failures and selected production traces into diagnoses, bounded changes, regression cases, and held-out validation.

```text
Product goal
    ↓
Representative eval cases
    ↓
Agent harness: prompt + context + tools + control flow
    ↓
Measured baseline
    ↓
Failures and production evidence
    ↓
Diagnosis → repair → held-in and held-out validation
    ↺
```

The repository is opinionated about sequence: do not optimize prompts before you can state the user outcome and evaluate it; do not accept a repair until it survives a test beyond the case that motivated it.

## Building a first agent

Start at `/onboard`. The first-build flow takes you through:

1. `/agent-goal-interview` — creates a brief with the target users, product problem, business value, scope, risks, and success metrics.
2. `/agent-eval-designer` — designs the eval suite, including simulated users, deterministic checks where possible, qualitative rubrics where necessary, and held-out coverage.
3. `/agent-architecture-planner` — produces an architecture picture and an implementation handoff derived from the goal and evals.
4. `/spec-plan` and `/agent-build-loop`, or your preferred engineering loop — implements the agreed handoff.
5. `/eval-agent` — runs a baseline evaluation against the completed target agent.

The output is not merely a working demo. It is a target agent plus an artifact trail explaining what it is meant to do, how it is tested, and which baseline results it achieved.

## Designing test cases and running evals

An eval case represents a user interaction rather than an isolated prompt/response. It combines:

- A **simulated user**: motivation, private context, questions, disclosure behavior, and desired outcome.
- A **scenario**: the conditions and conversation the agent must navigate.
- **Evaluators**: outcome checks, trajectory expectations such as tool use, and/or narrow qualitative rubrics.

The simulated user and target agent converse. The evaluation run captures the conversation and grades the resulting behavior. Use deterministic checks for facts, schemas, tool calls, and other stable properties. Use model-based judges only for behavior that genuinely requires qualitative judgment, with a constrained rubric.

Cases that expose a known defect become **held-in** regression coverage. Similar cases are kept **held-out** so a fix has to generalize rather than overfit the example. This distinction is what turns a collection of demos into an evaluation suite.

## Improving an existing agent

When an agent has a failing eval, suspicious behavior, or a useful production trace, run:

```text
/agent-lifecycle-orchestrator
```

The improvement flow can start from formal eval artifacts or selected production evidence. It diagnoses failure ownership—agent behavior, harness/context, tool integration, or the evaluation itself—then routes either a direct evidence repair or an engineering handoff. Agent changes are validated against held-in and held-out cases before the learning is folded back into the suite.

## Core concepts

| Term | Meaning |
|---|---|
| **Target agent** | The LLM-based system being built or improved, including its prompt, context, tools, state, and control flow. |
| **Agent harness** | The code and configuration that invokes the model, assembles context, exposes tools, manages state, and returns behavior to the user. |
| **Eval** | A repeatable experiment that measures whether the target agent satisfies a defined behavior or user outcome. |
| **Simulated user** | A model-driven user with a goal and private context, used to produce realistic multi-turn interactions. |
| **Trajectory** | The sequence of messages, tool calls, state changes, and outcomes produced during an agent interaction. |
| **Held-in case** | A known scenario used for development and regression prevention. |
| **Held-out case** | An unseen scenario reserved to test whether a change generalizes. |
| **Production evidence** | A selected and locally redacted trace used as evidence for diagnosis and improvement. |
| **Baseline** | The measured behavior of a particular agent version before an improvement attempt. |

## What happens during setup

Onboarding creates a local Python environment, installs the repository dependencies, creates `.env` from `.env.example` when needed, installs the repository's commit check, and verifies the Claude Code and Codex adapters.

Model-provider keys are optional individually: configure only the providers you choose for simulation and judging. Langfuse is optional and is used when you want remote traces, datasets, experiments, or production evidence. See [evaluation result providers](docs/references/eval-result-providers.md) for the exact options.

## Evaluation infrastructure

Local execution and remote observability are intentionally separate:

| Component | Why it is here | Do you need an account? |
|---|---|---|
| LangSmith Python package | Runs local evaluations without uploading results to LangSmith. | No |
| AgentEvals | Scores agent behavior, including expected tool-use sequences. | Only a selected judge model when needed |
| OpenEvals | Provides model-based judges and multi-turn simulated-user conversations. | Only a selected simulator or judge model |
| Langfuse | Optionally stores remote traces, datasets, experiments, and production evidence. | Yes, if you use it |
| pytest | Tests the repository's lifecycle, artifacts, adapters, and evaluation gates. | No |

LangChain and LangGraph may be recommended when they fit the target agent. They are not requirements for the agent you build.

## Useful references

- [Core concepts glossary](docs/references/core-concepts-glossary.md) — a fuller explanation of the terms used by the workflow.
- [Agent-building best practices](docs/references/agent-building-best-practices.md) — the maintained engineering guidance behind architecture and improvement recommendations.
- [Evaluation result providers](docs/references/eval-result-providers.md) — credentials and destinations for evaluation results.

## For people maintaining this repository

The repository works in both Claude Code and Codex. The manuals, skills, and project-agent configuration have shared sources of truth; see [`CLAUDE.md`](CLAUDE.md) before changing them. After changing those shared pieces, run:

```bash
scripts/test-agent-config.sh
```

## Full lifecycle map

Use this diagram when you want to see every stage and handoff. You do not need to memorize it: `/onboard` and `/agent-lifecycle-orchestrator` guide you to the relevant next step.

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
