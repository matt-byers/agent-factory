---
name: eval-agent
description: List and run repository agent eval cases through LangSmith's native evaluate interface, AgentEvals, OpenEvals, and the isolated JSONL target adapter. Use for local eval runs, diagnostic artifact capture, and held-in or held-out validation.
---

# Eval Agent

Run evals and produce evidence. Do not diagnose root causes or recommend target-agent changes.

## Commands

```bash
scripts/agent-eval list
scripts/agent-eval run --case <id> --target-command '<json-argument-array>' --simulator-model <provider:model> --judge-model <provider:model>
scripts/agent-eval run --case <id> --target-command '<json-argument-array>' --simulator-model <provider:model> --judge-model <provider:model> --artifacts
```

Local execution uses LangSmith `evaluate` with local examples and `upload_results=False`. AgentEvals owns trajectory evaluation, OpenEvals owns supported qualitative evaluators and multi-turn simulation, and repository evaluators are limited to declared deterministic invariants.

The target command must implement the JSONL `start`, `turn`, and `end` protocol. Each trial gets a new process. Target, provider, protocol, or evaluator failures are inconclusive and must not be reported as agent-quality rejections.

Use `--artifacts` only for the one diagnostic run that feeds behavior review. Validation and held-in/held-out reruns should not create diagnostic folders. Run held-in cases before releasing or running held-out cases.
