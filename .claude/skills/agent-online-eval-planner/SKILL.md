---
name: agent-online-eval-planner
description: Plan online evaluation before an agent becomes operational, then monitor scored production traces, select bounded expert-review batches, and route reviewed evidence into agent or eval improvement.
---

# Agent Online Eval Planner

Keep evaluation mode separate from result location:

- **Offline evaluation** runs a controlled agent version against a fixed dataset before release. It may run locally or as a remote Langfuse experiment.
- **Online evaluation** scores live production traces without rerunning the target agent.
- **Production evidence** is the bounded, reviewed trace evidence promoted from online monitoring into diagnosis or eval design.

Read `docs/references/online-offline-evaluation.md` and the Evaluation and observability section of `docs/references/agent-building-best-practices.md` before acting.

## Plan before architecture

Run only at lifecycle stage `online_eval_design` or when explicitly revising an existing online-eval plan. Read the complete eval suite and use `assets/online-eval-plan-template.yaml`.

For every online evaluator, bind:

- one or more offline eval case ids that define the behavior;
- the live trace or observation target;
- a deterministic code evaluator or narrow LLM-judge method;
- the provider score name, trace fields and input mappings;
- narrow production filters and a sampling rate;
- a score floor that selects failures rather than silently changing release gates.

Also define:

- the eligible trace population and production environment;
- the expert annotation queue, role, cadence and bounded failure quota;
- a random calibration sample in addition to threshold failures;
- whether missing scores enter review;
- content-capture approval, local redaction and retention;
- the canonical feedback routes.

If the target agent will not receive production traffic or production content cannot be captured safely, create an explicit disabled plan with a reason. Render and validate:

```bash
scripts/agent-online-eval render --input <online-eval-plan.json>
scripts/agent-online-eval validate
scripts/agent-lifecycle next
```

## Configure live scoring

Use Langfuse evaluator rules and annotation queues rather than building another UI or evaluator scheduler. Invoke a maintained host `/langfuse` capability when available; otherwise guide the operator through the provider UI or its documented API.

For each enabled evaluator:

1. Preview recent matching production data and verify every input mapping.
2. Test the evaluator on a small historical sample.
3. Configure the plan's trace filters and sampling percentage.
4. Record the provider evaluator/rule identifier in the plan when available.
5. Verify scores arrive on new matching traces before treating the plan as active.

Do not apply offline graders that require hidden reference answers to live traffic. Reuse only reference-free behavior criteria or deterministic checks whose required evidence exists in the trace. Provider and evaluator failures are inconclusive, never agent failures.

## Monitor

Query production traces with the plan's exact scope and retain the provider-reported eligible count. Include native scores and direct trace links, but keep raw content in provider memory unless a trace is selected.

Create a bounded query file with the plan's trace name, filter expression, ISO-8601 time window, page size and maximum pages, then run:

```bash
scripts/agent-online-eval inventory --query <online-trace-query.json>
```

The command writes the normalized inventory as:

```json
{
  "eligible_count": 1000,
  "traces": [
    {
      "trace_id": "provider-id",
      "source_link": "https://provider.example/trace",
      "scores": {"helpfulness": 0.72}
    }
  ]
}
```

Then run:

```bash
scripts/agent-online-eval report --traces <normalized-traces.json>
scripts/agent-online-eval review --traces <normalized-traces.json>
```

The report must preserve denominators: eligible, inspected, fully scored, missing/partial scores, failures, per-evaluator coverage and mean score. A bounded query that does not cover the eligible population must never present inspected counts as population counts.

## Expert review

Add the generated review-batch items to the plan's provider-native annotation queue. The batch contains direct links and scores, not copied conversation content. It prioritizes score-floor failures, optionally includes missing scores, and always retains the configured random calibration sample so experts can detect evaluator false positives and unobserved agent failures.

After review, assign exactly one disposition:

- `agent_failure` → promote the selected trace to `/agent-behavior-review` and the agent-improvement path.
- `eval_failure` → repair or recalibrate the evaluator/rubric and rerun affected evidence.
- `provider_failure` → repair instrumentation, mappings, permissions or evaluator execution.
- `new_coverage` → promote an eval candidate for expert validation and later offline regression coverage.

Copy the completed provider annotations into the batch's `expert_disposition` and `expert_comment` fields, then validate and render deterministic next actions:

```bash
scripts/agent-online-eval route-review
```

Never insert a production trace directly into held-out coverage. Redact selected evidence locally and deduplicate provider trace ids before promotion.
