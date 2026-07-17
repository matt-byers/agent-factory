from __future__ import annotations

from dataclasses import dataclass, field
from functools import wraps
from typing import Any, Callable, Mapping

from .target_adapter import redact_diagnostic


class EvalProviderError(RuntimeError):
    pass


@dataclass(frozen=True)
class EvalRunRequest:
    dataset_name: str
    experiment_name: str
    target: Callable[[dict[str, Any]], dict[str, Any]]
    examples: list[dict[str, Any]]
    evaluators: list[Callable[..., Any]]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalProviderResult:
    destination: str
    native_result: Any
    source_links: tuple[str, ...]
    _cleanup: Callable[[], None] = field(repr=False)
    _cleaned: bool = field(default=False, init=False, repr=False)

    def cleanup(self) -> None:
        if self._cleaned:
            return
        self._cleanup()
        self._cleaned = True


class LocalProvider:
    destination = "local"

    def __init__(self, runner: Any):
        self.runner = runner

    def run(self, request: EvalRunRequest) -> EvalProviderResult:
        try:
            result = self.runner.evaluate_local(
                request.target,
                request.examples,
                request.evaluators,
                request.experiment_name,
            )
        except Exception as error:
            raise _operation_error(self.destination, error) from error
        return EvalProviderResult(self.destination, result, (), lambda: None)


class LangSmithProvider:
    destination = "langsmith"

    def __init__(self, client: Any | None, evaluate_fn: Callable[..., Any] | None):
        self.client = client
        self.evaluate_fn = evaluate_fn

    def run(self, request: EvalRunRequest) -> EvalProviderResult:
        if self.client is None or self.evaluate_fn is None:
            raise EvalProviderError("LangSmith is not configured")
        try:
            dataset = self.client.create_dataset(
                dataset_name=request.dataset_name,
                description=f"Agent evaluation dataset for {request.experiment_name}",
            )
            self.client.create_examples(
                dataset_id=dataset.id,
                examples=[_langsmith_example(example) for example in request.examples],
            )
            result = self.evaluate_fn(
                request.target,
                data=dataset.name,
                evaluators=request.evaluators,
                experiment_prefix=request.experiment_name,
                upload_results=True,
                client=self.client,
                metadata=request.metadata,
            )
            experiment_name = str(
                getattr(result, "experiment_name", request.experiment_name)
            )
            links = _string_links(
                getattr(result, "experiment_url", None),
                getattr(result, "url", None),
            )
        except Exception as error:
            raise _operation_error(self.destination, error) from error

        def cleanup() -> None:
            try:
                self.client.delete_project(project_name=experiment_name)
                self.client.delete_dataset(dataset_id=dataset.id)
            except Exception as error:
                raise _operation_error(self.destination, error) from error

        return EvalProviderResult(self.destination, result, links, cleanup)

    def promote_trace(self, trace_id: str, dataset_id: str) -> None:
        if self.client is None:
            raise EvalProviderError("LangSmith is not configured")
        try:
            run = self.client.read_run(trace_id)
            self.client.create_example_from_run(run=run, dataset_id=dataset_id)
        except Exception as error:
            raise _operation_error(self.destination, error) from error


class LangfuseProvider:
    destination = "langfuse"

    def __init__(self, client: Any | None):
        self.client = client

    def run(self, request: EvalRunRequest) -> EvalProviderResult:
        if self.client is None:
            raise EvalProviderError("Langfuse is not configured")
        try:
            self.client.create_dataset(
                name=request.dataset_name,
                description=f"Agent evaluation dataset for {request.experiment_name}",
                metadata=request.metadata,
            )
            for example in request.examples:
                self.client.create_dataset_item(
                    dataset_name=request.dataset_name,
                    input=example.get("inputs", {}),
                    expected_output=example.get("outputs"),
                    metadata=example.get("metadata", {}),
                    source_trace_id=example.get("source_trace_id"),
                    source_observation_id=example.get("source_observation_id"),
                )
            dataset = self.client.get_dataset(request.dataset_name)
            result = dataset.run_experiment(
                name=request.experiment_name,
                description=f"Agent evaluation experiment {request.experiment_name}",
                task=_langfuse_task(request.target),
                evaluators=[_langfuse_evaluator(evaluator) for evaluator in request.evaluators],
                metadata=request.metadata,
            )
            links = tuple(
                link
                for trace_id in _langfuse_trace_ids(result)
                if (link := self.client.get_trace_url(trace_id=trace_id))
            )
            self.client.flush()
        except Exception as error:
            raise _operation_error(self.destination, error) from error

        def cleanup() -> None:
            try:
                self.client.api.datasets.delete(dataset_name=request.dataset_name)
                self.client.flush()
            except Exception as error:
                raise _operation_error(self.destination, error) from error

        return EvalProviderResult(self.destination, result, links, cleanup)


class EvalProviderRouter:
    def __init__(self, providers: Mapping[str, Any]):
        self.providers = dict(providers)

    def run(self, destination: str, request: EvalRunRequest) -> EvalProviderResult:
        provider = self.providers.get(destination)
        if provider is None:
            raise EvalProviderError(f"unsupported eval destination: {destination}")
        return provider.run(request)


def provider_capabilities() -> dict[str, dict[str, Any]]:
    return {
        "local": {
            "runner": "LangSmith evaluate/aevaluate",
            "upload_results": False,
            "native_resources": [],
        },
        "langsmith": {
            "runner": "LangSmith evaluate/aevaluate",
            "upload_results": True,
            "native_resources": ["datasets", "experiments", "scores", "traces"],
        },
        "langfuse": {
            "runner": "Langfuse dataset.run_experiment",
            "upload_results": True,
            "native_resources": [
                "traces",
                "observations",
                "datasets",
                "experiments",
                "scores",
            ],
        },
    }


def _langsmith_example(example: dict[str, Any]) -> dict[str, Any]:
    return {
        key: example[key]
        for key in ("inputs", "outputs", "metadata")
        if key in example
    }


def _langfuse_task(target: Callable[[dict[str, Any]], dict[str, Any]]) -> Callable[..., Any]:
    def task(*, item: Any, **_: Any) -> dict[str, Any]:
        return target(item.input)

    return task


def _langfuse_evaluator(evaluator: Callable[..., Any]) -> Callable[..., Any]:
    @wraps(evaluator)
    def evaluate(
        *,
        input: dict[str, Any],
        output: dict[str, Any],
        expected_output: dict[str, Any] | None = None,
        **_: Any,
    ) -> Any:
        return evaluator(
            inputs=input,
            outputs=output,
            reference_outputs=expected_output or {},
        )

    return evaluate


def _langfuse_trace_ids(result: Any) -> tuple[str, ...]:
    item_results = getattr(result, "item_results", [])
    return tuple(
        str(trace_id)
        for item in item_results
        if (trace_id := getattr(item, "trace_id", None))
    )


def _string_links(*values: Any) -> tuple[str, ...]:
    return tuple(str(value) for value in values if isinstance(value, str) and value)


def _operation_error(destination: str, error: Exception) -> EvalProviderError:
    message = redact_diagnostic(str(error))
    return EvalProviderError(f"{destination} provider operation failed: {message}")
