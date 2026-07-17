from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.eval_providers import (
    EvalProviderError,
    EvalProviderRouter,
    EvalRunRequest,
    LangfuseProvider,
    LocalProvider,
    provider_capabilities,
)


def request() -> EvalRunRequest:
    return EvalRunRequest(
        dataset_name="temporary-agent-eval",
        experiment_name="candidate-a",
        target=lambda inputs: {"answer": inputs["question"]},
        examples=[
            {
                "inputs": {"question": "hello"},
                "outputs": {"answer": "hello"},
                "metadata": {"split": "held_in"},
                "source_trace_id": "source-trace",
                "source_observation_id": "source-observation",
            }
        ],
        evaluators=[lambda outputs, reference_outputs: outputs == reference_outputs],
        metadata={"case": "greeting"},
    )


class RecordingRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def evaluate_local(self, target: Any, examples: Any, evaluators: Any, experiment_prefix: str) -> Any:
        self.calls.append(
            {
                "target": target,
                "data": examples,
                "evaluators": evaluators,
                "experiment_prefix": experiment_prefix,
                "upload_results": False,
            }
        )
        return SimpleNamespace(experiment_name=experiment_prefix)


def test_local_provider_uses_langsmith_runner_without_upload() -> None:
    runner = RecordingRunner()
    eval_request = request()

    result = LocalProvider(runner).run(eval_request)

    assert result.destination == "local"
    assert result.source_links == ()
    assert runner.calls == [
        {
            "target": eval_request.target,
            "data": eval_request.examples,
            "evaluators": eval_request.evaluators,
            "experiment_prefix": "candidate-a",
            "upload_results": False,
        }
    ]


@dataclass
class RecordingLangfuseExperimentResult:
    item_results: list[Any]


class RecordingLangfuseDataset:
    def __init__(self, calls: list[tuple[Any, ...]]) -> None:
        self.id = "lf-dataset-id"
        self.calls = calls

    def run_experiment(self, **kwargs: Any) -> RecordingLangfuseExperimentResult:
        self.calls.append(("run_experiment", kwargs))
        item = SimpleNamespace(input={"question": "hello"})
        assert kwargs["task"](item=item) == {"answer": "hello"}
        return RecordingLangfuseExperimentResult(
            item_results=[SimpleNamespace(trace_id="experiment-trace")]
        )


class RecordingLangfuseDatasetsApi:
    def __init__(self, calls: list[tuple[Any, ...]]) -> None:
        self.calls = calls

    def delete(self, **kwargs: Any) -> None:
        self.calls.append(("delete_dataset", kwargs))


class RecordingLangfuseClient:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []
        self.api = SimpleNamespace(datasets=RecordingLangfuseDatasetsApi(self.calls))

    def create_dataset(self, **kwargs: Any) -> Any:
        self.calls.append(("create_dataset", kwargs))
        return SimpleNamespace(id="lf-dataset-id", name=kwargs["name"])

    def create_dataset_item(self, **kwargs: Any) -> None:
        self.calls.append(("create_dataset_item", kwargs))

    def get_dataset(self, name: str) -> RecordingLangfuseDataset:
        self.calls.append(("get_dataset", name))
        return RecordingLangfuseDataset(self.calls)

    def get_trace_url(self, *, trace_id: str) -> str:
        self.calls.append(("get_trace_url", trace_id))
        return f"https://langfuse.example/traces/{trace_id}"

    def flush(self) -> None:
        self.calls.append(("flush",))


def test_langfuse_provider_uses_native_dataset_experiment_links_and_cleanup() -> None:
    client = RecordingLangfuseClient()

    result = LangfuseProvider(client).run(request())

    item_call = next(call for call in client.calls if call[0] == "create_dataset_item")
    assert item_call[1]["source_trace_id"] == "source-trace"
    assert item_call[1]["source_observation_id"] == "source-observation"
    assert any(call[0] == "run_experiment" for call in client.calls)
    assert result.source_links == ("https://langfuse.example/traces/experiment-trace",)
    assert client.calls[-1] == ("flush",)

    result.cleanup()

    assert ("delete_dataset", {"dataset_name": "temporary-agent-eval"}) in client.calls


def test_router_executes_exactly_one_selected_destination() -> None:
    calls: list[str] = []

    class RecordingProvider:
        def __init__(self, destination: str) -> None:
            self.destination = destination

        def run(self, _: EvalRunRequest) -> Any:
            calls.append(self.destination)
            return SimpleNamespace(destination=self.destination)

    router = EvalProviderRouter(
        {
            "local": RecordingProvider("local"),
            "langfuse": RecordingProvider("langfuse"),
        }
    )

    result = router.run("langfuse", request())

    assert result.destination == "langfuse"
    assert calls == ["langfuse"]


def test_unconfigured_langfuse_fails_without_falling_back() -> None:
    with pytest.raises(EvalProviderError, match="not configured"):
        LangfuseProvider(None).run(request())


def test_unknown_destination_is_rejected() -> None:
    with pytest.raises(EvalProviderError, match="unsupported eval destination"):
        EvalProviderRouter({"local": LocalProvider(RecordingRunner())}).run("other", request())


def test_provider_capabilities_document_native_ownership() -> None:
    capabilities = provider_capabilities()

    assert set(capabilities) == {"local", "langfuse"}
    assert capabilities["local"]["runner"] == "LangSmith evaluate/aevaluate"
    assert capabilities["local"]["upload_results"] is False
    assert capabilities["langfuse"]["native_resources"] == [
        "traces",
        "observations",
        "datasets",
        "experiments",
        "scores",
    ]


def test_provider_dependency_and_operator_docs_are_present() -> None:
    requirements = (REPOSITORY_ROOT / "requirements.txt").read_text(encoding="utf-8").splitlines()
    documentation = (
        REPOSITORY_ROOT / "docs/references/eval-result-providers.md"
    ).read_text(encoding="utf-8")
    skill = (
        REPOSITORY_ROOT / ".claude/skills/eval-agent/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "langfuse" in requirements
    assert "langsmith" in requirements
    assert "Local (`--destination local`)" in documentation
    assert "Langfuse (`--destination langfuse`)" in documentation
    assert "--destination langsmith" not in documentation
    assert "LANGSMITH_" not in documentation
    assert "Credentialed provider sandbox smoke: **Pending**" in documentation
    assert "docs/references/eval-result-providers.md" in skill
    assert "--destination <local|langfuse>" in skill
