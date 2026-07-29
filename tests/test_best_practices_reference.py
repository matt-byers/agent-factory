from __future__ import annotations

from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_PATH = REPOSITORY_ROOT / "docs" / "references" / "agent-building-best-practices.md"
CANONICAL_SOURCES = {
    "anthropic-architecture-pdf": "https://resources.anthropic.com/hubfs/Building%20Effective%20AI%20Agents-%20Architecture%20Patterns%20and%20Implementation%20Frameworks.pdf",
    "anthropic-tools": "https://www.anthropic.com/engineering/writing-tools-for-agents",
    "anthropic-context": "https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents",
    "openai-guide": "https://openai.com/business/guides-and-resources/a-practical-guide-to-building-ai-agents/",
    "openai-context": "https://openai.github.io/openai-agents-python/context/",
    "langchain-agents": "https://docs.langchain.com/oss/python/langchain/agents",
    "langchain-tools": "https://docs.langchain.com/oss/python/langchain/tools",
    "langchain-context": "https://docs.langchain.com/oss/python/langchain/context-engineering",
    "langgraph-workflows": "https://docs.langchain.com/oss/python/langgraph/workflows-agents",
    "react-paper": "https://arxiv.org/abs/2210.03629",
    "harness-engineering": "https://lilianweng.github.io/posts/2026-07-04-harness/",
    "anthropic-agent-evals": "https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents",
    "openai-eval-best-practices": "https://developers.openai.com/api/docs/guides/evaluation-best-practices",
    "openai-trace-grading": "https://developers.openai.com/api/docs/guides/trace-grading",
    "google-agent-observability": "https://google.github.io/agents-cli/guide/observability/",
    "google-bigquery-agent-analytics": "https://google.github.io/agents-cli/guide/observability/bq-agent-analytics/",
    "langfuse-evaluation-concepts": "https://langfuse.com/docs/evaluation/core-concepts",
    "langfuse-annotation-queues": "https://langfuse.com/docs/evaluation/evaluation-methods/annotation-queues",
}

CONSUMERS = (
    ".claude/skills/agent-architecture-planner/SKILL.md",
    ".claude/skills/agent-behavior-review/SKILL.md",
    ".claude/skills/agent-self-improvement/SKILL.md",
    ".claude/skills/agent-online-eval-planner/SKILL.md",
)

REQUIRED_TOPICS = (
    "## Choosing the simplest architecture",
    "## Workflow and agent patterns",
    "## Tool design",
    "## Context and memory",
    "## Evaluation and observability",
    "## Safety, control, and failure recovery",
    "## Eval-grounded harness improvement",
    "## Recommendation checklist",
)


def read_reference() -> str:
    return REFERENCE_PATH.read_text(encoding="utf-8")


def markdown_urls(text: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\((https?://[^)]+)\)", text)


def test_canonical_source_inventory_has_stable_links_and_access_dates() -> None:
    reference = read_reference()
    source_section = reference.split("## Source inventory", 1)[1]

    assert set(markdown_urls(source_section)) == set(CANONICAL_SOURCES.values())
    for source_id, url in CANONICAL_SOURCES.items():
        assert markdown_urls(source_section).count(url) == 1, source_id
        row = next(line for line in source_section.splitlines() if url in line)
        assert re.search(r"\| 2026-07-(?:17|28) \|$", row), source_id


def test_reference_uses_public_paths_and_does_not_duplicate_the_canonical_pdf() -> None:
    reference = read_reference()
    lowered = reference.lower()

    assert "/users/" not in lowered
    assert "downloads/" not in lowered
    assert "file://" not in lowered
    assert "localhost" not in lowered
    assert "https://www.anthropic.com/engineering/building-effective-agents" not in reference
    assert reference.count(CANONICAL_SOURCES["anthropic-architecture-pdf"]) == 1


def test_reference_covers_required_agent_building_topics() -> None:
    reference = read_reference()

    for heading in REQUIRED_TOPICS:
        assert heading in reference

    required_guidance = (
        "model call",
        "single agent",
        "multi-agent",
        "sequential",
        "parallel",
        "evaluator-optimizer",
        "held-out",
        "trajectory",
        "human approval",
        "idempotent",
        "context window",
        "accept, reject, or inconclusive",
        "offline evaluation",
        "online evaluation",
        "random sample",
    )
    for phrase in required_guidance:
        assert phrase in reference.lower()


def test_each_source_and_consumer_is_represented_exactly_once() -> None:
    reference = read_reference()

    for source_id in CANONICAL_SOURCES:
        assert reference.count(f"`{source_id}`") == 1
    for consumer in CONSUMERS:
        assert reference.count(f"`{consumer}`") == 1


def test_existing_consuming_skills_link_to_the_reference() -> None:
    relative_reference = "docs/references/agent-building-best-practices.md"

    for consumer in CONSUMERS:
        consumer_path = REPOSITORY_ROOT / consumer
        if consumer_path.exists():
            assert relative_reference in consumer_path.read_text(encoding="utf-8"), consumer
