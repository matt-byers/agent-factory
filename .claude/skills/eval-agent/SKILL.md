---
name: eval-agent
description: List and run repository agent eval cases through LangSmith's native evaluate interface, AgentEvals, OpenEvals, and the isolated JSONL target adapter. Use for local eval runs, diagnostic artifact capture, and held-in or held-out validation.
---

# Eval Agent

Run evals and produce evidence. Do not diagnose root causes or recommend target-agent changes.

## Commands

```bash
scripts/agent-eval list
scripts/agent-eval run --case <id> --target-command '<json-argument-array>' --simulator-model <provider:model> --judge-model <provider:model> --destination <local|langfuse>
scripts/agent-eval run --case <id> --target-command '<json-argument-array>' --simulator-model <provider:model> --judge-model <provider:model> --destination local --artifacts
scripts/agent-eval baseline --results <complete-native-held-in-run.json> --target-command '<json-argument-array>'
scripts/agent-eval held-in --results <complete-candidate-held-in-run.json>
scripts/agent-eval held-out --results <complete-candidate-held-out-run.json>
```

Local execution uses LangSmith `evaluate` with local examples and `upload_results=False`; LangSmith is an internal runner dependency, not a hosted destination, and needs no account or key. The Langfuse destination creates one provider-native dataset experiment and never duplicates it locally. AgentEvals owns trajectory evaluation, OpenEvals owns supported qualitative evaluators and multi-turn simulation, and repository evaluators are limited to declared deterministic invariants. Provider capabilities, credentials, source links, and sandbox cleanup are documented in `docs/references/eval-result-providers.md`.

The target command must implement the JSONL `start`, `turn`, and `end` protocol. Each trial gets a new process. Target, provider, protocol, or evaluator failures are inconclusive and must not be reported as agent-quality rejections.

Use `--artifacts` only for the one diagnostic run that feeds behavior review. Validation and held-in/held-out reruns should not create diagnostic folders. Run held-in cases before releasing or running held-out cases.

For target-agent improvements, resume from the accepted engineering receipt and reconcile the architecture picture when the receipt requires it. Submit the complete held-in native run through `held-in`; only an accepted decision releases the sealed held-out payloads. Submit held-out results through `held-out`. The gate compares native quality scores, hard invariants, latency, and cost with the accepted baseline. Accepted held-out validation replaces the baseline atomically; rejected or inconclusive validation leaves it unchanged. Eval, evidence, provider, data, and harness repairs return to diagnosis and do not use these agent validation gates.

For first-build baseline validation, run every held-in case and trial through the same target command, retain their projected native trial artifacts in one complete run file, then invoke `baseline`. Only an accepted gate enters operational state and records the prompt/toolset hashes. Target-agent failures route to improvement; eval, provider, data, and harness failures produce one compact diagnostic and route to their owning repair path.
