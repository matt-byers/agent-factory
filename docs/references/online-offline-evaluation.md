# Offline and Online Evaluation

Use evaluation mode to describe **what data is evaluated and when**, and destination to describe **where the run and scores are stored**. Do not use local/remote as synonyms for offline/online.

## Definitions

| Term | Definition |
|---|---|
| Offline evaluation | Run a controlled version of the target agent against a fixed, versioned dataset without real-user impact. |
| Local offline evaluation | An offline run executed locally with results retained locally. |
| Remote offline experiment | An offline run whose dataset, experiment traces and scores are stored by Langfuse. |
| Online evaluation | Apply reference-free or production-observable evaluators to live production traces, normally asynchronously and on a filtered sample. The target agent is not rerun. |
| Production monitoring | Operational metrics and errors from live traffic. It may identify suspicious traces without assigning behavioral quality scores. |
| Production evidence | A bounded, locally redacted trace selected after automated or human review for diagnosis or eval design. |
| Expert annotation | A domain expert reads a selected conversation and records structured scores, corrections or a disposition. |

The current `scripts/agent-eval run --destination langfuse` path is a **remote offline experiment**. It is not online evaluation merely because Langfuse stores the result.

## One connected evaluation loop

```text
Offline: fixed cases → candidate agent run → graders → release decision
                                      ↓ deploy
Online:  live traces → filtered/sampled evaluators → score trends
                                      ↓
                    failures + missing scores + random calibration sample
                                      ↓
                          expert annotation and disposition
                            ↙          ↓            ↘
                    agent repair   eval repair   new offline case
                            ↘          ↓            ↙
                         held-in and held-out validation
```

Offline and online evaluation should reuse behavior definitions where the production trace contains the required evidence. Hidden reference answers, simulated-user private truth and sealed held-out criteria must never be exposed to an online evaluator.

## Plan online evaluation before operation

Every first build must produce `agent-lifecycle/evals/online-eval-plan.yaml` before architecture:

- `enabled` records the provider, eligible production trace population, filters, evaluator mappings, sampling, score floors, expert review policy, privacy constraints and feedback routes.
- `disabled` records why production evaluation is not applicable or cannot be performed safely.

For each enabled evaluator, start from an offline behavior requirement or case id. Decide whether the behavior can be observed from production trace data. Use deterministic code checks for objective contracts and a narrow, human-calibrated model judge only for semantic criteria.

## Measure coverage before quality

An online report must preserve these separate counts:

- provider-reported eligible traces in the time window;
- traces inspected by the bounded query;
- traces with every required score;
- traces with missing or partial scores;
- traces failing one or more score floors;
- per-evaluator score coverage, failures and aggregates;
- evaluator execution failures and delays where the provider exposes them.

Never report the number of fetched traces as the population when pagination or query bounds truncated the result. Low or uneven score coverage is an instrumentation/evaluator problem, not evidence that the agent is good.

## Select expert review without hiding evaluator errors

Review selection combines:

1. score-floor failures, capped to an explicit workload;
2. missing or partial scores when configured;
3. a deterministic random calibration sample of apparently passing traces.

Failure-only review can estimate neither false-positive evaluator errors nor failures that the evaluator missed. The calibration sample checks agreement between human experts and automated scoring and helps detect distribution drift.

Use Langfuse annotation queues and direct trace links rather than copying raw conversations into repository artifacts or building another review UI. Persist only identifiers, links, scores, selection reasons and final dispositions until a specific trace is promoted and locally redacted.

## Route reviewed evidence

Every completed review gets one owner:

- `agent_failure`: reproducible target-agent behavior enters behavior review and agent improvement.
- `eval_failure`: ambiguous task, bad rubric, mapping error or judge disagreement enters eval repair.
- `provider_failure`: missing trace data, permissions, evaluator execution or instrumentation enters evidence repair.
- `new_coverage`: valid uncovered behavior becomes an expert-validated candidate for the offline suite.

Do not insert a production trace directly into held-out coverage. Agent changes still require held-in then protected held-out validation.

## Provider implementation

Langfuse evaluator rules provide live observation filters, per-evaluator sampling and input mappings. Scores provide the common result object; score analytics and metrics APIs provide aggregate reporting; annotation queues provide expert review. Agent Factory stores the intent and selection contract while reusing those provider-native capabilities.

The provider APIs for programmatic evaluator-rule setup may evolve. Preview mappings and test on a small historical sample before enabling a rule. Treat provider, evaluator and mapping failures as inconclusive.

## Primary references

- [OpenAI, Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices) — continuous evaluation, production-derived cases, logging and human calibration.
- [OpenAI, Trace grading](https://developers.openai.com/api/docs/guides/trace-grading) — structured grading of end-to-end traces and filtered trace runs.
- [Anthropic, Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents) — automated evals, production monitoring, transcript review and human calibration as complementary layers.
- [Google Agents CLI, Observability](https://google.github.io/agents-cli/guide/observability/) — production traces, prompt-response logging and environment-specific content capture.
- [Google Agents CLI, BigQuery Agent Analytics](https://google.github.io/agents-cli/guide/observability/bq-agent-analytics/) — production conversation analysis, counts, error discovery and LLM-as-judge scoring.
- [Langfuse, Evaluation core concepts](https://langfuse.com/docs/evaluation/core-concepts) — offline experiments versus online scoring of live traces.
- [Langfuse, LLM-as-a-Judge](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge) — live filters, sampling, mappings, evaluator rules and historical backfills.
- [Langfuse, Annotation queues](https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues) — structured domain-expert review.
