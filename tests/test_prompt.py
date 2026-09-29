from __future__ import annotations

from harbor_rag.prompt import (
    SYSTEM_PROMPT,
    Source,
    build_converse_request,
    estimate_tokens,
    fit_to_budget,
    guarded_text_blocks,
    render_sources,
    select_sources,
)
from tests.fakes import fixture


def results() -> list[dict]:
    return fixture("retrieve_returns")["retrievalResults"]


def test_chunks_of_one_document_merge_into_one_source() -> None:
    sources = select_sources(results(), max_sources=3, min_score=0.35, relative_floor=0.8)
    assert [s.title for s in sources] == ["Standard return window", "Holiday return extension"]
    assert "delivery date" in sources[0].text
    assert "30 days" in sources[0].text
    assert [s.index for s in sources] == [1, 2]


def test_relative_floor_drops_much_weaker_chunks() -> None:
    sources = select_sources(results(), max_sources=4, min_score=0.1, relative_floor=0.8)
    assert all(s.score >= 0.71 * 0.8 for s in sources)
    assert "Opened electronics returns" not in [s.title for s in sources]


def test_absolute_min_score_leaves_nothing_for_an_off_topic_question() -> None:
    assert (
        select_sources(fixture("retrieve_empty")["retrievalResults"], max_sources=3, min_score=0.35, relative_floor=0.8)
        == []
    )


def test_max_sources_caps_documents() -> None:
    sources = select_sources(results(), max_sources=1, min_score=0.1, relative_floor=0.1)
    assert len(sources) == 1


def test_no_results_means_no_sources() -> None:
    assert select_sources([], max_sources=3, min_score=0.1, relative_floor=0.5) == []


def source(i: int, chars: int) -> Source:
    return Source(i, f"s3://b/{i}.md", f"T{i}", "returns", "x" * chars, 0.9)


def test_budget_keeps_sources_in_rank_order_until_full() -> None:
    kept = fit_to_budget([source(1, 400), source(2, 400), source(3, 400)], max_tokens=220)
    assert [s.index for s in kept] == [1, 2]


def test_budget_truncates_a_single_oversized_source() -> None:
    kept = fit_to_budget([source(1, 10_000)], max_tokens=100)
    assert len(kept) == 1
    assert estimate_tokens(kept[0].text) <= 100


def test_converse_request_has_the_exact_guarded_shape() -> None:
    sources = select_sources(results(), max_sources=3, min_score=0.35, relative_floor=0.8)
    request = build_converse_request(
        question="How long is the return window?",
        sources=sources,
        model_id="m",
        guardrail_id="g",
        guardrail_version="3",
        max_output_tokens=400,
    )
    assert request == {
        "modelId": "m",
        "system": [{"text": SYSTEM_PROMPT}],
        "messages": [
            {
                "role": "user",
                "content": [
                    {"guardContent": {"text": {"text": render_sources(sources), "qualifiers": ["grounding_source"]}}},
                    {
                        "guardContent": {
                            "text": {"text": "How long is the return window?", "qualifiers": ["query", "guard_content"]}
                        }
                    },
                ],
            }
        ],
        "inferenceConfig": {"maxTokens": 400, "temperature": 0.0},
        "guardrailConfig": {"guardrailIdentifier": "g", "guardrailVersion": "3", "trace": "enabled"},
    }
    assert render_sources(sources).startswith("[1] Standard return window")


def test_the_question_is_evaluated_by_every_guardrail_policy() -> None:
    """`query` alone would feed only the grounding check: prompt attacks, denied topics and PII would never see it."""
    question_block = guarded_text_blocks(question="q", context="c")[1]["text"]
    assert "guard_content" in question_block["qualifiers"]
    assert "query" in question_block["qualifiers"]


def test_sources_are_grounding_only() -> None:
    assert guarded_text_blocks(question="q", context="c")[0] == {
        "text": {"text": "c", "qualifiers": ["grounding_source"]}
    }
