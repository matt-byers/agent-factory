---
name: onboard
description: Set up a new Agent Factory clone, guide the user through required model-provider and optional Langfuse credentials one at a time, explain the initial-build and eval-led improvement flows, and hand off to the lifecycle orchestrator. Use after cloning or whenever setup and credential configuration are incomplete.
---

# Onboard

Prepare the repository without exposing credentials, orient the user to Agent Factory, and leave them with one clear next action.

Follow this repository-specific sequence exactly. Do not replace it with generic project discovery, dependency advice, architecture inspection, or starter-agent implementation. Do not build or modify the target agent, create evals, choose its architecture, or invoke the engineering loop during onboarding; `/agent-lifecycle-orchestrator` owns everything after this handoff.

## Repository setup

1. Run `scripts/agent-setup` and resolve local setup failures before continuing.
2. Run `scripts/agent-onboard status`. Report only configured or missing names; never read or display `.env` values.
3. Explain that at least one model-provider key is needed for the simulator and judge. More than one is needed only if the user selects models from different providers.

## Credentials

Work through credentials one at a time. Ask whether the user wants each provider, wait for that decision, then finish its setup before discussing the next provider. Never ask the user to paste a credential into chat or pass one in a command argument.

For each selected variable:

1. Give the official setup link and briefly state what to create.
2. Tell the user to run `scripts/agent-onboard set <VARIABLE>` in their own terminal. The prompt hides the value and writes it to the ignored local `.env` file.
3. After the user confirms completion, run `scripts/agent-onboard status <VARIABLE>` and continue only when it reports `true`.

Offer model providers in this order, allowing the user to skip any they will not use:

- `ANTHROPIC_API_KEY`: create a key at https://platform.claude.com/settings/keys.
- `OPENAI_API_KEY`: create a project API key at https://platform.openai.com/api-keys.
- `GOOGLE_API_KEY`: create a Gemini API key at https://aistudio.google.com/app/apikey.

Then explain that Langfuse is optional: offline evals can run locally without a hosted eval account, while Langfuse enables remotely stored offline experiments, online scoring of live production traces, expert annotation queues, and production-trace evidence. Remote storage does not by itself make an eval online. If selected, create project credentials using https://langfuse.com/docs/observability/get-started and configure these one at a time:

- `LANGFUSE_PUBLIC_KEY`
- `LANGFUSE_SECRET_KEY`
- `LANGFUSE_BASE_URL`, using the URL for the user's cloud region or self-hosted instance

Finish by running `scripts/agent-onboard status`. Do not require skipped providers and do not perform paid API calls merely to test a key.

## Introduce the lifecycle

Explain the two flows concisely:

- **Initial agent setup:** define the user problem and commercial value, design evals and a simulated user, plan the architecture, hand off implementation, and establish a measured baseline.
- **Online evaluation setup:** before architecture, define how live traces will be filtered, sampled, scored, reviewed by experts, and fed back—or explicitly record why online evaluation is disabled.
- **Evals-led self-improvement:** start from offline eval results, an expert-reviewed online failure, or another selected production trace; diagnose the behavior, make an evidence-linked change or eval repair, validate held-in and held-out cases, and repeat when useful.

Mention that Agent Factory changes only the agent harness and context. Its included tests-first engineering loop is interchangeable with another loop or a standard coding agent.

If the user wants more detail on repository components, share the overview in `repository-infrastructure.md` in this skill directory.

## Handoff

End with this exact direction:

> Onboarding is complete. To get started building your agent, invoke `/agent-lifecycle-orchestrator`.
