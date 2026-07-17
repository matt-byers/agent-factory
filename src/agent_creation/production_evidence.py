from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import hashlib
from itertools import islice
import json
from pathlib import Path
from typing import Any

from .target_adapter import redact_diagnostic


INDEX_PATH = Path("agent-lifecycle/evidence/production-evidence-index.json")
DIAGNOSTIC_PATH = Path("agent-lifecycle/evidence/selected-evidence.yaml")
EVAL_CANDIDATE_DIRECTORY = Path("agent-lifecycle/evals/candidates")
SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "access_token",
    "accesstoken",
    "authorization",
    "client_secret",
    "password",
    "secret",
    "token",
}


class EvidenceProviderError(RuntimeError):
    pass


class EvidencePromotionError(ValueError):
    pass


@dataclass(frozen=True)
class EvidenceQuery:
    project_name: str | None = None
    trace_name: str | None = None
    filter_expression: str | None = None
    from_timestamp: datetime | None = None
    to_timestamp: datetime | None = None
    page_size: int = 50
    max_pages: int = 10

    def __post_init__(self) -> None:
        if self.page_size < 1 or self.page_size > 100:
            raise ValueError("page_size must be between 1 and 100")
        if self.max_pages < 1:
            raise ValueError("max_pages must be positive")


@dataclass(frozen=True)
class ProductionTrace:
    provider: str
    trace_id: str
    name: str | None
    timestamp: str | None
    input: Any
    output: Any
    metadata: Any
    tags: tuple[str, ...]
    source_link: str


@dataclass(frozen=True)
class PromotionResult:
    fingerprint: str
    path: Path
    created: bool


def query_langsmith_traces(client: Any | None, query: EvidenceQuery) -> tuple[ProductionTrace, ...]:
    _require_client(client, "LangSmith")
    arguments = _without_none(
        {
            "project_name": query.project_name,
            "filter": query.filter_expression,
            "start_time": query.from_timestamp,
            "end_time": query.to_timestamp,
            "is_root": True,
            "limit": query.page_size * query.max_pages,
        }
    )
    try:
        runs = client.list_runs(**arguments)
        bounded_runs = islice(runs, query.page_size * query.max_pages)
        return tuple(
            _normalize_trace("langsmith", run, client.get_run_url(run=run))
            for run in bounded_runs
        )
    except Exception as error:
        raise _provider_error("langsmith", "query", error) from error


def query_langfuse_traces(client: Any | None, query: EvidenceQuery) -> tuple[ProductionTrace, ...]:
    _require_client(client, "Langfuse")
    traces: list[ProductionTrace] = []
    try:
        for page in range(1, query.max_pages + 1):
            arguments = _without_none(
                {
                    "name": query.trace_name,
                    "filter": query.filter_expression,
                    "from_timestamp": _isoformat(query.from_timestamp),
                    "to_timestamp": _isoformat(query.to_timestamp),
                    "fields": "core,io",
                    "limit": query.page_size,
                    "page": page,
                }
            )
            response = client.api.trace.list(**arguments)
            items = list(_value(response, "data", []))
            traces.extend(
                _normalize_trace(
                    "langfuse",
                    item,
                    client.get_trace_url(trace_id=str(_value(item, "id", ""))),
                )
                for item in items
            )
            total_pages = _value(_value(response, "meta", {}), "total_pages")
            if total_pages is None:
                total_pages = _value(_value(response, "meta", {}), "totalPages")
            if not items or len(items) < query.page_size or (
                isinstance(total_pages, int) and page >= total_pages
            ):
                break
        return tuple(traces)
    except Exception as error:
        raise _provider_error("langfuse", "query", error) from error


def select_langsmith_trace(client: Any | None, trace_id: str) -> ProductionTrace:
    _require_client(client, "LangSmith")
    _require_trace_id(trace_id)
    try:
        run = client.read_run(trace_id)
        return _normalize_trace("langsmith", run, client.get_run_url(run=run))
    except Exception as error:
        raise _provider_error("langsmith", "selection", error) from error


def select_langfuse_trace(client: Any | None, trace_id: str) -> ProductionTrace:
    _require_client(client, "Langfuse")
    _require_trace_id(trace_id)
    try:
        trace = client.api.trace.get(trace_id)
        return _normalize_trace(
            "langfuse", trace, client.get_trace_url(trace_id=trace_id)
        )
    except Exception as error:
        raise _provider_error("langfuse", "selection", error) from error


def promote_evidence(
    root: Path, trace: ProductionTrace, destination: str
) -> PromotionResult:
    if destination not in {"diagnostic", "eval"}:
        raise EvidencePromotionError("destination must be diagnostic or eval")
    fingerprint = _fingerprint(trace, destination)
    index_path = root / INDEX_PATH
    index = _read_index(index_path)
    existing = index.get(fingerprint)
    if isinstance(existing, dict):
        relative_path = _promotion_path(fingerprint, destination)
        if existing.get("path") != relative_path.as_posix() or not (root / relative_path).is_file():
            raise EvidencePromotionError("production evidence index contains a stale or unsafe path")
        return PromotionResult(fingerprint, root / relative_path, False)
    relative_path = _promotion_path(fingerprint, destination)
    artifact = {
        "schema_version": 1,
        "kind": destination,
        "fingerprint": fingerprint,
        "evidence": _redact(asdict(trace)),
    }
    _atomic_write(root / relative_path, artifact)
    if destination == "diagnostic":
        index = {
            key: value
            for key, value in index.items()
            if not isinstance(value, dict) or value.get("destination") != "diagnostic"
        }
    index[fingerprint] = {
        "destination": destination,
        "path": relative_path.as_posix(),
        "provider": trace.provider,
        "trace_id": trace.trace_id,
    }
    _atomic_write(index_path, index)
    return PromotionResult(fingerprint, root / relative_path, True)


def cleanup_promotion(root: Path, fingerprint: str) -> Path | None:
    index_path = root / INDEX_PATH
    index = _read_index(index_path)
    entry = index.get(fingerprint)
    if not isinstance(entry, dict):
        return None
    destination = entry.get("destination")
    if destination not in {"diagnostic", "eval"}:
        raise EvidencePromotionError("production evidence index contains an unsafe destination")
    relative_path = _promotion_path(fingerprint, destination)
    if entry.get("path") != relative_path.as_posix():
        raise EvidencePromotionError("production evidence index contains an unsafe path")
    path = root / relative_path
    if path.is_file():
        payload = _read_json(path, "promoted evidence")
        if payload.get("fingerprint") != fingerprint:
            raise EvidencePromotionError("refusing to delete a replaced evidence artifact")
        path.unlink()
    del index[fingerprint]
    _atomic_write(index_path, index)
    return path


def cleanup_langsmith_trace(client: Any | None, trace_id: str) -> None:
    _require_client(client, "LangSmith")
    _require_trace_id(trace_id)
    try:
        client.delete_run(trace_id)
    except Exception as error:
        raise _provider_error("langsmith", "cleanup", error) from error


def cleanup_langfuse_trace(client: Any | None, trace_id: str) -> None:
    _require_client(client, "Langfuse")
    _require_trace_id(trace_id)
    try:
        client.api.trace.delete(trace_id)
        client.flush()
    except Exception as error:
        raise _provider_error("langfuse", "cleanup", error) from error


def _normalize_trace(provider: str, trace: Any, source_link: str) -> ProductionTrace:
    trace_id = str(_value(trace, "id", ""))
    if not trace_id:
        raise ValueError("provider trace is missing an id")
    timestamp = _value(trace, "start_time")
    if timestamp is None:
        timestamp = _value(trace, "timestamp")
    return ProductionTrace(
        provider=provider,
        trace_id=trace_id,
        name=_value(trace, "name"),
        timestamp=_isoformat(timestamp),
        input=_redact(_value(trace, "input", _value(trace, "inputs"))),
        output=_redact(_value(trace, "output", _value(trace, "outputs"))),
        metadata=_redact(_value(trace, "metadata", _value(trace, "extra", {}))),
        tags=tuple(str(tag) for tag in _value(trace, "tags", []) or []),
        source_link=redact_diagnostic(str(source_link)),
    )


def _redact(value: Any, key: str | None = None) -> Any:
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return "[redacted]"
    if isinstance(value, dict):
        return {str(item_key): _redact(item_value, str(item_key)) for item_key, item_value in value.items()}
    if isinstance(value, (list, tuple)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        return redact_diagnostic(value)
    return value


def _fingerprint(trace: ProductionTrace, destination: str) -> str:
    identity = {
        "destination": destination,
        "provider": trace.provider,
        "trace_id": trace.trace_id,
    }
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _promotion_path(fingerprint: str, destination: str) -> Path:
    if destination == "diagnostic":
        return DIAGNOSTIC_PATH
    return EVAL_CANDIDATE_DIRECTORY / f"{fingerprint}.json"


def _read_index(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return _read_json(path, "production evidence index")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvidencePromotionError(f"{label} is not valid JSON: {path}") from error
    if not isinstance(payload, dict):
        raise EvidencePromotionError(f"{label} must be an object: {path}")
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _value(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    return getattr(value, name, default)


def _without_none(values: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def _isoformat(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _require_client(client: Any | None, provider: str) -> None:
    if client is None:
        raise EvidenceProviderError(f"{provider} is not configured")


def _require_trace_id(trace_id: str) -> None:
    if not isinstance(trace_id, str) or not trace_id.strip():
        raise ValueError("trace_id must be non-empty")


def _provider_error(provider: str, operation: str, error: Exception) -> EvidenceProviderError:
    return EvidenceProviderError(
        f"{provider} {operation} failed: {redact_diagnostic(str(error))}"
    )
