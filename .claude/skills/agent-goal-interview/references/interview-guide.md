# Interview Guide

## Understand the job

- Who directly uses or is affected by the agent?
- What problem are they trying to solve, and how do they handle it today?
- What specific purpose should the agent serve?
- What belongs in scope, what is excluded, and which agent harness or context surfaces may change?
- What can fail, and what is the failure cost of each important failure?

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
