# Agent-Building Best Practices

Last verified: 2026-07-17

This maintained reference turns the source inventory below into decision guidance for architecture planning, behavior review, and evidence-driven improvement. It is guidance, not a substitute for current provider documentation or evaluation against the target use case. Recommendations should cite the relevant source marker, requirement or evidence, expected effect, and acceptance eval.

## Choosing the simplest architecture

Choose the least autonomous shape that can reliably satisfy the measured outcome. Complexity is a cost in latency, tokens, failure modes, security surface, and diagnosis effort; add it only when representative evals expose a limitation in the simpler shape. [S1] [S4]

1. Use a model call when one bounded inference can produce a verifiable result and no environment interaction or adaptive control flow is needed.
2. Use a workflow when the steps, branches, and stopping conditions are known in advance. Keep deterministic routing, validation, retries, and state transitions in code.
3. Use a single agent when the task requires dynamic tool choice, recovery, or an unpredictable number and order of steps within one coherent domain.
4. Use a multi-agent system only when eval evidence shows that one agent cannot manage separable domains, parallel exploration, tool overload, or context boundaries. Define why each agent exists, what it owns, and how its output is verified.

Start with a capable model to establish a quality baseline, then test whether smaller or faster models can meet each call's acceptance criteria. Keep model, prompt, tools, and policy modular so they can evolve independently. [S1] [S4]

Escalating architecture must produce a measurable benefit over its predecessor. Compare task success, safety, latency, token and provider cost, recovery rate, and operator burden on the same held-in and held-out cases. If the benefit is absent or inconclusive, retain the simpler design.

## Workflow and agent patterns

Use patterns as composable control-flow tools, not as goals by themselves. [S1] [S6] [S9]

- Prompt chaining or a sequential workflow fits stages with linear dependencies and explicit intermediate checks. Stop early when a gate fails.
- Routing classifies an input and sends it to a specialized model, prompt, toolset, or workflow. Make the route set closed and test ambiguous and out-of-scope inputs.
- Parallel workflows fit independent subtasks or independent candidate generation. Bound fan-out and define deterministic aggregation, conflict handling, timeout, and partial-failure behavior.
- Orchestrator-worker systems fit tasks whose subtasks cannot be enumerated in advance. The orchestrator delegates bounded work; workers receive only the context and tools they need; the orchestrator verifies before synthesis.
- Evaluator-optimizer loops fit outputs with objective, repeatable evaluation criteria and meaningful revision headroom. Cap iterations and stop on success, no progress, cost limit, or evaluator failure.
- A single agent fits open-ended execution in one domain. Give it an explicit objective, constrained tools, state, budgets, and stopping conditions.
- Multi-agent coordination fits genuinely distinct domains or context partitions. Prefer centralized supervision when ownership and auditability matter; use decentralized collaboration only when peer coordination itself is necessary and can be evaluated.

LangChain agents run on LangGraph and are suitable when a standard tool-calling loop plus middleware is enough. Use LangGraph directly for custom state, durable execution, interrupts, or mixed deterministic and agentic nodes. In both cases, make state transitions and termination observable. [S6] [S9]

## Tool design

Tools are contracts between non-deterministic model behavior and deterministic systems. Design them around high-value agent tasks rather than mirroring every backend endpoint. A small set of distinct, composable tools is easier to select and evaluate than many overlapping tools. [S2] [S7]

- Give every tool one clear purpose and a name that distinguishes it from neighboring tools. Namespace large inventories consistently.
- Use strict, typed schemas; descriptive parameter names; domain vocabulary; realistic examples; and explicit constraints. Validate in code rather than relying on the model to obey prose.
- Return compact, decision-relevant data with stable field names. Offer bounded filtering, pagination, or concise and detailed response modes rather than flooding the context window.
- Return typed, actionable errors that explain whether the agent should correct input, retry, choose another action, or stop. Preserve machine-readable error identity.
- Make safe mutations idempotent where possible. Inject identity, authorization scope, and server-owned identifiers outside model-controlled arguments.
- Separate reads from writes. Require human approval or an equivalent policy gate for destructive, irreversible, high-impact, or externally visible actions.
- Set timeouts, retry budgets, rate and cost limits, and output-size limits. Do not retry non-transient failures blindly.
- Test tool selection, valid and malformed arguments, empty and oversized results, permission failures, partial failures, duplicate calls, and recovery trajectories.

Tool quality is empirical. Prototype against realistic tasks, inspect raw calls and results, measure errors and unnecessary calls, and improve the schema, description, payload, or deterministic implementation before adding task-specific prompt patches. Validate improvements on held-out cases. [S2]

## Context and memory

Treat context as a finite attention budget whose value usually declines as irrelevant material accumulates. Supply the smallest coherent set of instructions, state, history, retrieved evidence, tool definitions, and tool results needed for the next decision. [S3] [S5] [S8]

Keep three concerns distinct:

- Runtime context is dependency and request data available to code and tools but not automatically shown to the model, such as authenticated identity, clients, and policy configuration.
- Model context is the prompt-visible message history, instructions, tool definitions, retrieved material, and current task state.
- Long-term memory is information persisted across runs and retrieved deliberately. It needs ownership, provenance, expiry, correction, privacy, and relevance rules.

Prefer selective retrieval, progressive disclosure, compaction, structured notes, and external state over retaining an ever-growing transcript. Preserve commitments, unresolved work, provenance, and identifiers needed for continuation when summarizing. Keep source data outside the context until it is relevant.

Measure context changes with task success, retrieval precision, token use, latency, and failure trajectories. More context is not automatically safer or more capable. Treat retrieved content and tool output as untrusted data, delimit it from instructions, and prevent it from silently changing policy or tool authority.

## Evaluation and observability

Define success before architecture. Build representative cases from real tasks, risks, and boundary conditions; include deterministic checks, output rubrics, trajectory checks, and a realistic simulated user when interaction matters. Keep an inaccessible held-out set for selection control. [S2] [S10]

Evaluate both the result and the path:

- Outcome measures cover correctness, completeness, user value, safety, and required side effects.
- Trajectory measures cover tool choice, arguments, ordering, state transitions, recovery, forbidden actions, and stopping behavior without demanding one exact path when several are valid.
- Operational measures cover latency, model and tool calls, token and provider cost, retries, errors, and human escalations.

Retain enough trace evidence to reproduce and assign failures: versioned prompt and model configuration, input, messages, tool calls and results, state transitions, errors, usage, timing, termination reason, and artifact identifiers. Redact secrets and sensitive data at the persistence boundary. Do not infer hidden reasoning from prose; diagnose observable decisions and effects.

Use deterministic evaluators for contracts and invariants, structured rubrics for qualities that need judgment, and multiple trials when model variance can change the conclusion. Provider or harness failures are inconclusive evidence, not target-agent regressions.

## Safety, control, and failure recovery

Autonomy must be bounded by code-owned policy. Use layered controls: least-privilege tools, authenticated server context, input and output validation, allowlists, sandboxing where appropriate, network and data boundaries, budgets, timeouts, maximum steps, and audit logs. [S1] [S4]

Place human approval before consequential actions when uncertainty or impact warrants it. The approval must show the intended action and material parameters, and the resumed run must bind approval to that exact action rather than accepting a generic confirmation.

Define explicit terminal states for success, safe refusal, human escalation, timeout, budget exhaustion, dependency failure, and unrecoverable tool error. Persist checkpoints only when replay is safe; use idempotency keys or reconciliation for side effects. Test interruption, resume, duplicate delivery, stale state, malformed tool output, and partial completion.

Assume external content can contain prompt injection. Keep instructions and evidence structurally separate, constrain which content may influence actions, and never grant authority merely because retrieved text requests it.

## Eval-grounded harness improvement

Improve the harness through an evidence loop rather than accumulating instructions after every failure. The harness includes prompts, context assembly, tools and wrappers, control flow, model configuration, memory, skills, and subagent configuration. [S11]

1. Capture a reproducible failure with the smallest sufficient transcript, trace, state, and evaluator evidence.
2. Assign ownership to target-agent behavior, the eval, the harness, evidence quality, provider infrastructure, or the surrounding application. Do not propose a target-agent change for an externally owned failure.
3. Form one bounded hypothesis that connects the evidence to a harness surface and predicts an observable effect.
4. Prefer the smallest general fix: repair a deterministic contract, expose missing context, improve a tool, adjust control flow, or clarify a durable instruction. Avoid example-specific prompt patches unless the behavior is genuinely policy.
5. Run affected held-in cases first, then the protected held-out gate. Compare quality, safety, trajectory, latency, and cost against baseline.
6. Record the evidence and decide to accept, reject, or inconclusive. An inconclusive result cannot justify shipping the candidate.
7. Retain the full diagnostic evidence once and compact decision artifacts for repeated validation. Promote repeatable production failures into eval cases.

Review the harness itself for stale or contradictory instructions, missing tools, noisy context, ambiguous ownership, evaluator leakage, and incentives that reward the wrong outcome. Delete or consolidate guidance when a deterministic mechanism makes it redundant.

## Recommendation checklist

Every architecture, review, or improvement recommendation should answer:

- What requirement, eval result, transcript, or production trace motivates it?
- Which source rationale supports it, and where does project evidence override generic guidance?
- Why is the proposed shape no more complex than necessary?
- Which agent-owned prompt, context, tool, workflow, state, model, memory, skill, or subagent surface changes?
- What surrounding-application dependency remains external and unchanged?
- What observable benefit and possible regression are expected?
- Which deterministic test, held-in eval, and held-out eval will accept or reject it?
- What safety boundary, approval point, budget, stopping condition, and recovery behavior apply?
- What evidence and version metadata must be retained for diagnosis and rollback?

## Consumers

The canonical consumers are listed here before their implementation units create them. Once present, each skill must link directly to this reference and cite it when using its guidance:

- `.claude/skills/agent-architecture-planner/SKILL.md`
- `.claude/skills/agent-behavior-review/SKILL.md`
- `.claude/skills/agent-self-improvement/SKILL.md`

## Source inventory

The Anthropic PDF is the canonical architecture source; the similarly named engineering article is intentionally excluded to avoid duplicate ingestion. Access dates record the most recent link and guidance review.

| Marker | Source ID | Source and rationale | Accessed |
|---|---|---|---|
| S1 | `anthropic-architecture-pdf` | [Anthropic, *Building Effective AI Agents: Architecture Patterns and Implementation Frameworks*](https://resources.anthropic.com/hubfs/Building%20Effective%20AI%20Agents-%20Architecture%20Patterns%20and%20Implementation%20Frameworks.pdf) — architecture selection, modularity, single-agent and multi-agent patterns, workflows, observability, context, and governance. | 2026-07-17 |
| S2 | `anthropic-tools` | [Anthropic, *Writing effective tools for agents*](https://www.anthropic.com/engineering/writing-tools-for-agents) — task-oriented tools, schemas, context-efficient results, errors, and eval-driven tool improvement. | 2026-07-17 |
| S3 | `anthropic-context` | [Anthropic, *Effective context engineering for AI agents*](https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents) — finite attention, context selection, compaction, retrieval, and long-horizon operation. | 2026-07-17 |
| S4 | `openai-guide` | [OpenAI, *A practical guide to building agents*](https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/) — agent foundations, model and tool selection, orchestration, guardrails, and human intervention. | 2026-07-17 |
| S5 | `openai-context` | [OpenAI Agents SDK, *Context management*](https://openai.github.io/openai-agents-python/context/) — local runtime context versus model-visible context. | 2026-07-17 |
| S6 | `langchain-agents` | [LangChain, *Agents*](https://docs.langchain.com/oss/python/langchain/agents) — current agent loop, middleware, tools, state, and structured output. | 2026-07-17 |
| S7 | `langchain-tools` | [LangChain, *Tools*](https://docs.langchain.com/oss/python/langchain/tools) — tool schemas, runtime context, state, stores, and tool-call control. | 2026-07-17 |
| S8 | `langchain-context` | [LangChain, *Context engineering in agents*](https://docs.langchain.com/oss/python/langchain/context-engineering) — model, tool, and lifecycle context strategies. | 2026-07-17 |
| S9 | `langgraph-workflows` | [LangGraph, *Workflows and agents*](https://docs.langchain.com/oss/python/langgraph/workflows-agents) — routing, parallelization, orchestrator-worker, evaluator-optimizer, and agent patterns. | 2026-07-17 |
| S10 | `react-paper` | [Yao et al., *ReAct: Synergizing Reasoning and Acting in Language Models*](https://arxiv.org/abs/2210.03629) — interleaved reasoning and environment actions as an agent design and evaluation foundation. | 2026-07-17 |
| S11 | `harness-engineering` | [Lilian Weng, *Harness Engineering for Self-Improvement*](https://lilianweng.github.io/posts/2026-07-04-harness/) — eval-grounded diagnosis, bounded harness changes, validation, and compounding improvement. | 2026-07-17 |
