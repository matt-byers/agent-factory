# Interview Guide

## Understand the job

- Who directly uses or is affected by the agent?
- What problem are they trying to solve, and how do they handle it today?
- What specific purpose should the agent serve?
- What belongs in scope, what is excluded, and which agent harness or context surfaces may change?
- What can fail, and what is the failure cost of each important failure?

## Gather real-world material for evaluation

The downstream eval designer builds a golden dataset of task specifications from
real failures, not imagined ones. Surface that raw material now:

- Are there existing transcripts, tickets, or logs? What recurring intents or
  request types appear, and which ones go wrong most often?
- Where should the agent refuse, escalate to a human, or decline rather than
  act? Capture these should-not situations alongside the should-do ones so the
  suite can test both sides.
- How do real users actually behave — vague, impatient, changing their mind,
  withholding detail? Name the difficult behaviors to encode, not just the
  cooperative path.
- What policy or compliance constraints govern the flow, so adherence can be
  scored separately from whether the task got done?
- How reliable must the behavior be — acceptable occasionally, or correct every
  time? Record where users expect every-time reliability.

## Establish trade-offs

Ask the user to rank accuracy, latency, and cost from first to third and explain each rank. Resolve contradictory rankings or constraints explicitly.

## Define outcomes

For each user or business outcome, capture:

- A lowercase hyphen-case identifier.
- Whether it is a user or business outcome.
- A concrete description of good.
- How someone will observe that the outcome occurred.

## Define success metrics

For every outcome, capture at least one linked metric with:

- Metric identifier and name.
- Direction of improvement.
- Baseline value, unit, and source.
- Target value in the same unit.
- Data source, accountable owner, and measurement cadence.

Do not accept proxy activity as value without connecting it to a user or business outcome. Ask a focused follow-up whenever a required value is unknown.

## Model commercial value and unit economics

For conservative, base, and upside scenarios, capture eligible volume, expected adoption, baseline and target success, attribution, revenue and gross margin, time savings and loaded labor cost, error or rework avoidance, loss avoidance, variable run cost, fixed cost, and implementation cost.

Record an assumption, source, and owner for every input. Assign each revenue, time-saving, rework-avoidance, and loss-avoidance benefit a distinct economic unit; reject double counting when two benefits claim the same unit.

Review annual gross and net value, contribution per adopted task, value per successful outcome, maximum viable run cost, break-even volume, adoption and quality, and payback period. Resolve contradictions and scenario boundaries before accepting the model.
