"""Retrieval metrics at document level (a chunk counts for the document it came from)."""

from __future__ import annotations

from collections.abc import Sequence


def ranked_docs(doc_ids: Sequence[str]) -> list[str]:
    """Document IDs in first-seen order: several chunks of one document count once, at their best rank."""
    seen: list[str] = []
    for doc_id in doc_ids:
        if doc_id not in seen:
            seen.append(doc_id)
    return seen


def recall_at_k(ranked: Sequence[str], relevant: Sequence[str], k: int) -> float:
    if not relevant:
        raise ValueError("recall is undefined without relevant documents")
    return len(set(ranked[:k]) & set(relevant)) / len(set(relevant))


def reciprocal_rank(ranked: Sequence[str], relevant: Sequence[str]) -> float:
    for rank, doc_id in enumerate(ranked, start=1):
        if doc_id in relevant:
            return 1.0 / rank
    return 0.0


def citation_precision(cited: Sequence[str], relevant: Sequence[str]) -> float:
    """Share of the sources the ask function would show the model (and so could cite) that are relevant.

    An empty selection scores 0: for an answerable question, citing nothing is a failure.
    """
    if not cited:
        return 0.0
    return sum(1 for d in cited if d in relevant) / len(cited)
