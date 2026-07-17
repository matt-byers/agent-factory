from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterator
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.production_evidence import (
    EvidencePromotionError,
    EvidenceProviderError,
    EvidenceQuery,
    cleanup_langfuse_trace,
    cleanup_langsmith_trace,
    cleanup_promotion,
    promote_evidence,
    query_langfuse_traces,
    query_langsmith_traces,
    select_langfuse_trace,
    select_langsmith_trace,
)


SECRET = "production-secret-value"
START = datetime(2026, 7, 1, tzinfo=timezone.utc)
END = datetime(2026, 7, 18, tzinfo=timezone.utc)


def trace(identifier: str, *, duplicate_secret: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=identifier,
        name="shopping-agent",
        start_time=START,
        input={"message": f"token={SECRET}" if duplicate_secret else "hello"},
        output={"answer": "Bearer dangerous-token"},
        metadata={"api_key": SECRET, "environment": "production"},
        tags=["production", "failure"],
    )


class RecordingLangSmithClient:
    def __init__(self, runs: list[Any] | None = None) -> None:
        self.runs = runs or []
        self.calls: list[tuple[str, Any]] = []

    def list_runs(self, **kwargs: Any) -> Iterator[Any]:
        self.calls.append(("list_runs", kwargs))
        yield from self.runs

    def read_run(self, run_id: str) -> Any:
        self.calls.append(("read_run", run_id))
        return next(item for item in self.runs if item.id == run_id)

    def get_run_url(self, *, run: Any) -> str:
        self.calls.append(("get_run_url", run.id))
        return f"https://smith.example/projects/prod/r/{run.id}"

    def delete_run(self, run_id: str) -> None:
        self.calls.append(("delete_run", run_id))


class RecordingLangfuseTraceApi:
    def __init__(self, pages: dict[int, list[Any]]) -> None:
        self.pages = pages
        self.calls: list[tuple[str, Any]] = []

    def list(self, **kwargs: Any) -> Any:
        self.calls.append(("list", kwargs))
        page = kwargs["page"]
        return SimpleNamespace(
            data=self.pages.get(page, []),
            meta=SimpleNamespace(total_pages=max(self.pages, default=1)),
        )

    def get(self, trace_id: str) -> Any:
        self.calls.append(("get", trace_id))
        return next(item for items in self.pages.values() for item in items if item.id == trace_id)

    def delete(self, trace_id: str) -> None:
        self.calls.append(("delete", trace_id))


class RecordingLangfuseClient:
    def __init__(self, pages: dict[int, list[Any]]) -> None:
        self.trace_api = RecordingLangfuseTraceApi(pages)
        self.api = SimpleNamespace(trace=self.trace_api)
        self.calls: list[tuple[str, Any]] = []

    def get_trace_url(self, *, trace_id: str) -> str:
        self.calls.append(("get_trace_url", trace_id))
        return f"https://langfuse.example/project/prod/traces/{trace_id}"

    def flush(self) -> None:
        self.calls.append(("flush", None))


def evidence_query() -> EvidenceQuery:
    return EvidenceQuery(
        project_name="production-agent",
        trace_name="shopping-agent",
        filter_expression='and(eq(status, "error"), has(tags, "failure"))',
        from_timestamp=START,
        to_timestamp=END,
        page_size=2,
        max_pages=2,
    )


def test_langsmith_query_uses_native_filters_and_bounded_lazy_pagination() -> None:
    client = RecordingLangSmithClient(
        [trace("ls-1"), trace("ls-2"), trace("ls-3"), trace("ls-4"), trace("ls-5")]
    )

    traces = query_langsmith_traces(client, evidence_query())

    assert [item.trace_id for item in traces] == ["ls-1", "ls-2", "ls-3", "ls-4"]
    assert traces[0].source_link.endswith("/ls-1")
    assert client.calls[0] == (
        "list_runs",
        {
            "project_name": "production-agent",
            "filter": 'and(eq(status, "error"), has(tags, "failure"))',
            "start_time": START,
            "end_time": END,
            "is_root": True,
            "limit": 4,
        },
    )


def test_langfuse_query_filters_and_pages_through_native_trace_api() -> None:
    client = RecordingLangfuseClient({1: [trace("lf-1"), trace("lf-2")], 2: [trace("lf-3")]})

    traces = query_langfuse_traces(client, evidence_query())

    assert [item.trace_id for item in traces] == ["lf-1", "lf-2", "lf-3"]
    list_calls = [call for call in client.trace_api.calls if call[0] == "list"]
    assert [call[1]["page"] for call in list_calls] == [1, 2]
    assert list_calls[0][1] == {
        "name": "shopping-agent",
        "filter": 'and(eq(status, "error"), has(tags, "failure"))',
        "from_timestamp": START.isoformat(),
        "to_timestamp": END.isoformat(),
        "fields": "core,io",
        "limit": 2,
        "page": 1,
    }


def test_exact_trace_selection_retains_provider_source_links() -> None:
    langsmith = RecordingLangSmithClient([trace("ls-selected")])
    langfuse = RecordingLangfuseClient({1: [trace("lf-selected")]})

    selected_langsmith = select_langsmith_trace(langsmith, "ls-selected")
    selected_langfuse = select_langfuse_trace(langfuse, "lf-selected")

    assert selected_langsmith.source_link == "https://smith.example/projects/prod/r/ls-selected"
    assert selected_langfuse.source_link == "https://langfuse.example/project/prod/traces/lf-selected"
    assert ("read_run", "ls-selected") in langsmith.calls
    assert ("get", "lf-selected") in langfuse.trace_api.calls


def test_langsmith_selection_supports_native_plural_io_fields() -> None:
    run = SimpleNamespace(
        id="native-run",
        name="agent",
        start_time=START,
        inputs={"message": "hello"},
        outputs={"answer": "world"},
        extra={"runtime": "production"},
        tags=["production"],
    )

    selected = select_langsmith_trace(RecordingLangSmithClient([run]), "native-run")

    assert selected.input == {"message": "hello"}
    assert selected.output == {"answer": "world"}
    assert selected.metadata == {"runtime": "production"}


@pytest.mark.parametrize("destination", ["diagnostic", "eval"])
def test_promotion_redacts_nested_secrets_and_deduplicates(tmp_path: Path, destination: str) -> None:
    selected = select_langsmith_trace(
        RecordingLangSmithClient([trace("same-trace")]), "same-trace"
    )

    first = promote_evidence(tmp_path, selected, destination)
    second = promote_evidence(tmp_path, selected, destination)

    assert first.created is True
    assert second.created is False
    assert second.path == first.path
    persisted = first.path.read_text(encoding="utf-8")
    assert SECRET not in persisted
    assert "dangerous-token" not in persisted
    assert "[redacted]" in persisted
    assert selected.source_link in persisted
    assert len(json.loads((tmp_path / "agent-lifecycle/evidence/production-evidence-index.json").read_text())) == 1
    if destination == "diagnostic":
        assert first.path == tmp_path / "agent-lifecycle/evidence/selected-evidence.yaml"
    else:
        assert first.path.parent == tmp_path / "agent-lifecycle/evals/candidates"


def test_cleanup_removes_only_selected_provider_trace_and_local_promotion(tmp_path: Path) -> None:
    langsmith = RecordingLangSmithClient([trace("temporary-ls")])
    langfuse = RecordingLangfuseClient({1: [trace("temporary-lf")]})
    promotion = promote_evidence(
        tmp_path,
        select_langsmith_trace(langsmith, "temporary-ls"),
        "eval",
    )

    cleanup_langsmith_trace(langsmith, "temporary-ls")
    cleanup_langfuse_trace(langfuse, "temporary-lf")
    removed = cleanup_promotion(tmp_path, promotion.fingerprint)

    assert ("delete_run", "temporary-ls") in langsmith.calls
    assert ("delete", "temporary-lf") in langfuse.trace_api.calls
    assert langfuse.calls[-1] == ("flush", None)
    assert removed == promotion.path
    assert not promotion.path.exists()
    assert json.loads((tmp_path / "agent-lifecycle/evidence/production-evidence-index.json").read_text()) == {}


def test_cleanup_rejects_a_tampered_index_path(tmp_path: Path) -> None:
    promotion = promote_evidence(
        tmp_path,
        select_langsmith_trace(RecordingLangSmithClient([trace("safe")]), "safe"),
        "eval",
    )
    index_path = tmp_path / "agent-lifecycle/evidence/production-evidence-index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))
    index[promotion.fingerprint]["path"] = "../../outside.json"
    index_path.write_text(json.dumps(index), encoding="utf-8")

    with pytest.raises(EvidencePromotionError, match="unsafe path"):
        cleanup_promotion(tmp_path, promotion.fingerprint)


@pytest.mark.parametrize(
    "operation",
    [
        lambda: query_langsmith_traces(None, evidence_query()),
        lambda: query_langfuse_traces(None, evidence_query()),
        lambda: select_langsmith_trace(None, "trace"),
        lambda: select_langfuse_trace(None, "trace"),
    ],
)
def test_unavailable_providers_fail_without_fallback(operation: Any) -> None:
    with pytest.raises(EvidenceProviderError, match="not configured"):
        operation()


def test_provider_failures_are_redacted_and_identify_the_operation() -> None:
    class BrokenClient:
        def list_runs(self, **_: Any) -> Any:
            raise RuntimeError(f"api_key={SECRET}")

    with pytest.raises(EvidenceProviderError) as error:
        query_langsmith_traces(BrokenClient(), evidence_query())

    assert "langsmith query failed" in str(error.value)
    assert SECRET not in str(error.value)


def test_skill_documents_query_promote_smoke_cleanup_and_pending_credentials() -> None:
    skill = (
        REPOSITORY_ROOT / ".claude/skills/agent-production-evidence/SKILL.md"
    ).read_text(encoding="utf-8")

    assert "## Query" in skill
    assert "## Promote" in skill
    assert "## Smoke" in skill
    assert "## Cleanup" in skill
    assert "/langfuse" in skill
    assert "LangSmith" in skill
    assert "Pending" in skill
