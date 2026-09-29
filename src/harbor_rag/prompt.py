"""Context selection, token budget and the Converse request.

The function builds its own prompt instead of calling `RetrieveAndGenerate` (ADR 0003): it decides which chunks are
good enough to show the model, keeps the context inside a token budget, and marks the context and the question for the
guardrail's contextual grounding check.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

SYSTEM_PROMPT = (
    "You answer questions from Harbor Goods store staff using only the numbered policy sources provided. "
    "Cite every statement with the number of its source in square brackets, for example [1]. "
    "If the sources do not answer the question, reply exactly: NO_ANSWER. "
    "Do not give legal advice, do not discuss competitors' prices, and never repeat personal data."
)
NO_ANSWER = "NO_ANSWER"


@dataclass(frozen=True)
class Source:
    index: int
    uri: str
    title: str
    doc_type: str
    text: str
    score: float


def estimate_tokens(text: str) -> int:
    """About four characters per token for English text. Used for budgeting only; billing uses the API's counts."""
    return max(1, math.ceil(len(text) / 4))


def _uri(result: Mapping[str, Any]) -> str:
    location = result.get("location", {})
    return str(location.get("s3Location", {}).get("uri", "")) or str(
        result.get("metadata", {}).get("x-amz-bedrock-kb-source-uri", "unknown")
    )


def select_sources(
    results: Sequence[Mapping[str, Any]], *, max_sources: int, min_score: float, relative_floor: float
) -> list[Source]:
    """Keep the chunks worth showing the model, one source per document.

    A chunk is kept when its score is at least `min_score` (absolute: below it, the knowledge base found nothing
    relevant) and at least `relative_floor` times the best score (relative: much weaker than the best match, it
    usually comes from another policy and invites a wrong citation). Chunks of the same document are merged into one
    source, in score order, so a citation always points at a document.
    """
    ranked = sorted(results, key=lambda r: float(r.get("score", 0.0)), reverse=True)
    if not ranked:
        return []
    top = float(ranked[0].get("score", 0.0))
    floor = max(min_score, top * relative_floor)
    merged: dict[str, Source] = {}
    for result in ranked:
        score = float(result.get("score", 0.0))
        if score < floor:
            break
        uri = _uri(result)
        text = str(result.get("content", {}).get("text", "")).strip()
        if uri in merged:
            existing = merged[uri]
            if text not in existing.text:
                merged[uri] = replace(existing, text=existing.text + "\n...\n" + text)
            continue
        if len(merged) == max_sources:
            continue
        metadata = result.get("metadata", {})
        merged[uri] = Source(
            index=len(merged) + 1,
            uri=uri,
            title=str(metadata.get("title", uri.rsplit("/", 1)[-1])),
            doc_type=str(metadata.get("doc_type", "unknown")),
            text=text,
            score=score,
        )
    return list(merged.values())


def fit_to_budget(sources: Sequence[Source], max_tokens: int) -> list[Source]:
    """Keep sources in rank order while they fit; truncate the first one if it alone is over budget."""
    kept: list[Source] = []
    used = 0
    for source in sources:
        cost = estimate_tokens(source.text)
        if used + cost <= max_tokens:
            kept.append(source)
            used += cost
        elif not kept:
            kept.append(replace(source, text=source.text[: max_tokens * 4]))
            break
        else:
            break
    return kept


def render_sources(sources: Sequence[Source]) -> str:
    return "\n\n".join(f"[{s.index}] {s.title}\n{s.text}" for s in sources)


# Qualifiers decide which guardrail policies see a block (Bedrock user guide, "Use contextual grounding check"):
#   grounding_source alone: the grounding reference only, not evaluated by any other policy;
#   query alone: the grounding query only, not evaluated by any other policy;
#   query + guard_content: the grounding query, and evaluated by every other policy (denied topics, content filters
#   including prompt attacks, sensitive information).
# The question is user input, so it carries both. The sources are our own documents: grounding only.
SOURCE_QUALIFIERS = ["grounding_source"]
QUESTION_QUALIFIERS = ["query", "guard_content"]


def guarded_text_blocks(*, question: str, context: str) -> list[dict[str, Any]]:
    """The two guarded text blocks, in the shape shared by `Converse` (inside `guardContent`) and `ApplyGuardrail`."""
    return [
        {"text": {"text": context, "qualifiers": list(SOURCE_QUALIFIERS)}},
        {"text": {"text": question, "qualifiers": list(QUESTION_QUALIFIERS)}},
    ]


def build_converse_request(
    *,
    question: str,
    sources: Sequence[Source],
    model_id: str,
    guardrail_id: str,
    guardrail_version: str,
    max_output_tokens: int,
) -> dict[str, Any]:
    """A Converse request with the guardrail attached.

    The sources go in a `guardContent` block qualified `grounding_source`, and the question in one qualified `query`
    and `guard_content`: the contextual grounding and relevance checks compare the answer against both, and the
    question is also screened for prompt attacks, denied topics, harmful content and PII.
    """
    blocks = guarded_text_blocks(question=question, context=render_sources(sources))
    return {
        "modelId": model_id,
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [{"role": "user", "content": [{"guardContent": block} for block in blocks]}],
        "inferenceConfig": {"maxTokens": max_output_tokens, "temperature": 0.0},
        "guardrailConfig": {
            "guardrailIdentifier": guardrail_id,
            "guardrailVersion": guardrail_version,
            "trace": "enabled",
        },
    }
