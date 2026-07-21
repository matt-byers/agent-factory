"""Deterministic intent clustering for eval case generation.

Groups free-text items (transcript openings, ticket subjects, existing case
openings) into intent clusters without any model call or randomness, so the same
corpus always yields the same clusters. The eval designer uses this to see which
intents a corpus contains, ensure the suite covers each, and detect a single
intent crowding out the rest.

The method is token-overlap union-find: normalize each item to a salient-token
set, union any two items whose Jaccard overlap meets a fixed threshold, then
label each cluster by its most common shared terms. It is intentionally simple
and inspectable rather than statistically optimal.
"""

from __future__ import annotations

from collections import Counter
import re
from typing import Any


TOKEN = re.compile(r"[a-z0-9]+")
DEFAULT_THRESHOLD = 0.3
DEFAULT_MIN_TOKEN_LENGTH = 3
STOPWORDS = frozenset(
    {
        "the", "and", "you", "your", "for", "are", "was", "were", "this", "that",
        "with", "but", "not", "can", "could", "would", "should", "want", "need",
        "please", "thanks", "thank", "hello", "hey", "have", "has", "had", "get",
        "got", "about", "from", "they", "them", "why", "how", "what", "when",
        "where", "which", "who", "does", "did", "been", "just", "also", "into",
        "than", "then", "there", "their", "some", "any", "our", "out",
    }
)


class ClusteringError(ValueError):
    def __init__(self, issues: list[str]):
        self.issues = issues
        super().__init__("; ".join(issues))


def normalize_tokens(text: str, min_token_length: int = DEFAULT_MIN_TOKEN_LENGTH) -> frozenset[str]:
    """Return the deduplicated salient tokens of ``text``."""

    return frozenset(
        token
        for token in TOKEN.findall(text.casefold())
        if len(token) >= min_token_length and token not in STOPWORDS
    )


def _jaccard(left: frozenset[str], right: frozenset[str]) -> float:
    if not left or not right:
        return 0.0
    intersection = len(left & right)
    if not intersection:
        return 0.0
    return intersection / len(left | right)


class _UnionFind:
    def __init__(self, size: int):
        self.parent = list(range(size))

    def find(self, node: int) -> int:
        while self.parent[node] != node:
            self.parent[node] = self.parent[self.parent[node]]
            node = self.parent[node]
        return node

    def union(self, left: int, right: int) -> None:
        left_root, right_root = self.find(left), self.find(right)
        if left_root == right_root:
            return
        # Attach the higher-indexed root under the lower one for stable roots.
        low, high = sorted((left_root, right_root))
        self.parent[high] = low


def normalize_items(items: Any) -> list[dict[str, str]]:
    """Coerce input into ``[{"id", "text"}]`` and reject malformed corpora."""

    if not isinstance(items, list) or not items:
        raise ClusteringError(["items must be a non-empty list"])
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    issues: list[str] = []
    for index, item in enumerate(items):
        if isinstance(item, str):
            identifier, text = f"item-{index}", item
        elif isinstance(item, dict):
            identifier = item.get("id") or f"item-{index}"
            text = item.get("text", "")
        else:
            issues.append(f"items[{index}] must be a string or object")
            continue
        if not isinstance(identifier, str) or not identifier.strip():
            issues.append(f"items[{index}].id must be a non-empty string")
            continue
        if not isinstance(text, str):
            issues.append(f"items[{index}].text must be a string")
            continue
        if identifier in seen:
            issues.append(f"items[{index}].id is duplicated: {identifier}")
            continue
        seen.add(identifier)
        normalized.append({"id": identifier, "text": text})
    if issues:
        raise ClusteringError(issues)
    return normalized


def _label(token_sets: list[frozenset[str]], terms_in_label: int = 3) -> tuple[str, list[str]]:
    frequencies: Counter[str] = Counter()
    for tokens in token_sets:
        frequencies.update(tokens)
    if not frequencies:
        return "unlabeled", []
    ranked = sorted(frequencies, key=lambda token: (-frequencies[token], token))
    terms = ranked[:terms_in_label]
    return "-".join(terms), terms


def cluster_intents(
    items: Any,
    threshold: float = DEFAULT_THRESHOLD,
    min_token_length: int = DEFAULT_MIN_TOKEN_LENGTH,
) -> list[dict[str, Any]]:
    """Cluster ``items`` by intent and return clusters sorted deterministically.

    Each cluster is ``{"label", "size", "terms", "member_ids"}``. Items with no
    salient tokens collapse into a single ``unlabeled`` cluster.
    """

    if not 0 < threshold <= 1:
        raise ClusteringError(["threshold must be within (0, 1]"])
    records = normalize_items(items)
    token_sets = [normalize_tokens(record["text"], min_token_length) for record in records]

    union_find = _UnionFind(len(records))
    empty_indexes = [index for index, tokens in enumerate(token_sets) if not tokens]
    for anchor in empty_indexes[1:]:
        union_find.union(empty_indexes[0], anchor)
    for left in range(len(records)):
        if not token_sets[left]:
            continue
        for right in range(left + 1, len(records)):
            if token_sets[right] and _jaccard(token_sets[left], token_sets[right]) >= threshold:
                union_find.union(left, right)

    grouped: dict[int, list[int]] = {}
    for index in range(len(records)):
        grouped.setdefault(union_find.find(index), []).append(index)

    clusters: list[dict[str, Any]] = []
    for members in grouped.values():
        label, terms = _label([token_sets[index] for index in members])
        clusters.append(
            {
                "label": label,
                "size": len(members),
                "terms": terms,
                "member_ids": [records[index]["id"] for index in members],
            }
        )
    clusters.sort(key=lambda cluster: (-cluster["size"], cluster["label"]))
    return clusters
