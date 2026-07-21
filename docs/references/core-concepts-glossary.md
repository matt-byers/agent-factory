# Core Concepts Glossary

Definitions for the layered vocabulary used throughout this repository. Containment order:

```
harness ⊃ agent loop ⊃ context function → context
```

The harness runs the loop, each loop turn runs the context function, and each run of the context function emits a context — the one thing the model actually sees.

## Context

The actual text in the model's window on a single call: system prompt, instructions, retrieved documents, examples, memory entries, conversation history, tool results. It is pure data, rebuilt for every call, and it is the only lever available over a frozen model's behavior. One call's briefing packet.

## Context function

The recipe that produces the context. A mapping from a specific input to a finished briefing packet: given query `x`, it returns the assembled context for that query. It consists of the static material available for inclusion (knowledge, rules, examples) plus the selection logic (retrieval, filtering, ordering) that decides what makes it into a particular call. Context is the *output*; the context function is the *generator*. This is the primary target of context-improvement work.

## Agent loop

The core cycle that makes a model into an agent: build context → call the model → parse its response → if it requested an action, execute the action and append the result to the context → repeat until done. It is the `while` loop itself. Each turn invokes the context function once and grows the context with whatever came back.

## Agent harness

The whole software vehicle around the model, of which the agent loop is the engine. It contains the loop, the context function, and everything else needed to run safely in the real world: tool implementations, permission checks, retries and error handling, memory persistence, stop conditions, logging. Harness is the broadest term; the other three nest inside it.

## How improvement work maps onto these layers

Layered picture, innermost out: **model** (frozen weights) → **context** (text the model reads this call) → **harness** (code that builds context and executes what the model says) → **improvement loop** (edits the context function and parts of the harness) → **meta layer** (edits the improvement loop itself). Each layer steers the one inside it.

This repository's lifecycle mutates the target agent's context function, mostly leaves the loop and the rest of the harness fixed, and never touches model weights. The repository's own skills form the meta layer: procedures that govern how the improvement loop operates.

Reference: [Lilian Weng, "Meta Context Engineering" (2026)](https://lilianweng.github.io/posts/2026-07-04-harness/) uses the same decomposition — a base-agent edits the target's context function, and a meta-agent evolves the procedure the base-agent follows.
