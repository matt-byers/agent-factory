from __future__ import annotations

from pathlib import Path
import sys

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPOSITORY_ROOT / "src"))

from agent_creation.intent_clustering import (
    ClusteringError,
    cluster_intents,
    normalize_tokens,
)


CORPUS = [
    {"id": "t1", "text": "I want a refund for my cancelled order"},
    {"id": "t2", "text": "Please process a refund on this order, it was cancelled"},
    {"id": "t3", "text": "How do I add a beneficiary to my will?"},
    {"id": "t4", "text": "I need to add another beneficiary to the will"},
    {"id": "t5", "text": "My executor question is about the estate"},
]


def labels(clusters: list[dict]) -> list[str]:
    return [cluster["label"] for cluster in clusters]


def cluster_of(clusters: list[dict], member: str) -> dict:
    return next(cluster for cluster in clusters if member in cluster["member_ids"])


def test_stopwords_and_short_tokens_are_dropped() -> None:
    tokens = normalize_tokens("I want a refund for my cancelled ORDER")

    assert tokens == frozenset({"refund", "cancelled", "order"})


def test_similar_intents_cluster_and_distinct_intents_separate() -> None:
    clusters = cluster_intents(CORPUS)

    assert cluster_of(clusters, "t1") == cluster_of(clusters, "t2")
    assert cluster_of(clusters, "t3") == cluster_of(clusters, "t4")
    assert cluster_of(clusters, "t1") != cluster_of(clusters, "t3")
    refund_cluster = cluster_of(clusters, "t1")
    assert "refund" in refund_cluster["label"]
    assert refund_cluster["size"] == 2


def test_clustering_is_deterministic_and_order_independent() -> None:
    forward = cluster_intents(CORPUS)
    again = cluster_intents(CORPUS)
    reversed_input = cluster_intents(list(reversed(CORPUS)))

    def signature(clusters: list[dict]) -> list[tuple]:
        return [(cluster["label"], tuple(sorted(cluster["member_ids"]))) for cluster in clusters]

    assert forward == again
    assert signature(forward) == signature(reversed_input)


def test_output_is_sorted_by_size_then_label() -> None:
    clusters = cluster_intents(CORPUS)

    keys = [(-cluster["size"], cluster["label"]) for cluster in clusters]
    assert keys == sorted(keys)


def test_items_without_salient_tokens_collapse_into_one_unlabeled_cluster() -> None:
    clusters = cluster_intents([{"id": "a", "text": "..."}, {"id": "b", "text": "the a to"}])

    assert len(clusters) == 1
    assert clusters[0]["label"] == "unlabeled"
    assert sorted(clusters[0]["member_ids"]) == ["a", "b"]


def test_plain_string_items_are_accepted() -> None:
    clusters = cluster_intents(["refund my order please", "refund the order now"])

    assert len(clusters) == 1
    assert clusters[0]["size"] == 2


def test_threshold_must_be_within_unit_interval() -> None:
    with pytest.raises(ClusteringError, match="threshold"):
        cluster_intents(CORPUS, threshold=0)


def test_empty_and_duplicate_corpora_are_rejected() -> None:
    with pytest.raises(ClusteringError, match="non-empty list"):
        cluster_intents([])
    with pytest.raises(ClusteringError, match="duplicated"):
        cluster_intents([{"id": "x", "text": "one"}, {"id": "x", "text": "two"}])
