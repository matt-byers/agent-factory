# Eval result providers

Every eval selection runs exactly once through one destination. Provider adapters record the native result; they do not create a second local experiment.

## Capabilities

- Local (`--destination local`) uses LangSmith `evaluate`/`aevaluate` with the Unit 2.2 evaluator functions and `upload_results=False`. It creates no remote dataset, experiment, score, or trace.
- Langfuse (`--destination langfuse`) creates native dataset items with optional source trace and observation links, runs one native dataset experiment, stores evaluator outputs as native scores, flushes the short-lived client, and returns trace links.

LangSmith is an internal local-runner dependency only. It needs no LangSmith account, environment variables, or remote upload. Langfuse is the only remote destination. Missing Langfuse credentials or provider failures are inconclusive evidence and never fall back to local execution automatically.

## Configuration

Local mode needs only the selected simulator and judge model credentials. Langfuse uses `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`.

Provider credentials belong in the ignored `.env` file and must never be passed in command arguments, committed artifacts, or chat. Source trace inputs and returned source links may identify provider resources, but adapters redact credential-shaped values from provider errors.

## Temporary sandbox cleanup

Recording-client tests verify dataset creation, experiment selection, source links, flushing, cleanup, unavailable credentials, and prevention of duplicate experiments without network access. For a credentialed sandbox smoke, use unique temporary dataset and experiment names, retain their identifiers and source links, query the result, call the returned cleanup operation, and verify the temporary resources are gone.

Credentialed provider sandbox smoke: **Pending** per the implementation spec because provider accounts and credentials are user-controlled.
