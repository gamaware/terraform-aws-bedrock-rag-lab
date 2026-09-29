from __future__ import annotations

import pytest

from harbor_rag.config import Settings
from harbor_rag.service import (
    REFUSAL,
    InvalidQuestionError,
    ThrottledError,
    UpstreamError,
    answer_question,
    call_with_retries,
)
from tests.fakes import FakeBedrock, client_error, fixture


def ask(port: FakeBedrock, settings: Settings, question: str = "How long do customers have to return items?"):
    return answer_question(question, port=port, settings=settings, sleep=lambda _: None)


def test_answer_with_citations_and_usage(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_answer")])
    answer = ask(port, settings)
    assert not answer.refused
    assert answer.reason == "answered"
    assert [c["title"] for c in answer.citations] == ["Standard return window", "Holiday return extension"]
    assert answer.citations[0]["uri"].endswith("returns/returns-standard-window.md")
    assert answer.usage == {"inputTokens": 412, "outputTokens": 58}
    assert answer.guardrail == {"action": "NONE", "findings": []}


def test_no_context_refuses_without_calling_the_model(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_empty")])
    answer = ask(port, settings, "What is the parental leave policy?")
    assert answer.refused
    assert answer.reason == "no_context"
    assert answer.answer == REFUSAL
    assert answer.guardrail["action"] == "NOT_EVALUATED"
    assert port.converse_calls == []


def test_answer_without_citation_is_replaced_by_the_refusal(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_no_citation")])
    answer = ask(port, settings)
    assert answer.refused
    assert answer.reason == "no_citation"
    assert answer.answer == REFUSAL


def test_citation_to_a_source_that_was_not_given_does_not_count(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_bad_citation")])
    answer = ask(port, settings)
    assert answer.refused
    assert answer.reason == "no_citation"


def test_model_declining_is_a_refusal(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_no_answer")])
    answer = ask(port, settings)
    assert (answer.refused, answer.reason) == (True, "model_declined")


def test_denied_topic_returns_the_guardrail_message_and_finding(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_guardrail_topic")])
    answer = ask(port, settings, "Can the customer sue us over the return?")
    assert answer.refused
    assert answer.reason == "guardrail"
    assert answer.guardrail == {"action": "INTERVENED", "findings": ["topic:legal-advice:BLOCKED"]}
    assert "can't help" in answer.answer
    assert answer.citations == []


def test_grounding_block_reports_the_policy_not_the_text(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_guardrail_grounding")])
    answer = ask(port, settings)
    assert answer.guardrail["findings"] == ["grounding:GROUNDING:BLOCKED", "pii:EMAIL:ANONYMIZED"]
    assert answer.reason == "guardrail"


def test_question_is_redacted_before_retrieve_and_before_the_model(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_answer")])
    answer = ask(port, settings, "Customer jane@example.com, card 4111 1111 1111 1111: return window?")
    sent = port.retrieve_calls[0]["query"]
    assert "jane@example.com" not in sent
    assert "4111" not in sent
    assert "{EMAIL}" in sent
    query_block = port.converse_calls[0]["messages"][0]["content"][1]["guardContent"]["text"]["text"]
    assert query_block == sent
    assert answer.redacted == ["EMAIL", "CREDIT_DEBIT_CARD_NUMBER"]


def test_doc_type_filter_and_settings_reach_retrieve(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_answer")])
    answer_question("Return window?", port=port, settings=settings, doc_type="returns", sleep=lambda _: None)
    call = port.retrieve_calls[0]
    assert call == {"knowledge_base_id": "KBHARBOR01", "query": "Return window?", "n": 8, "doc_type": "returns"}
    assert port.converse_calls[0]["modelId"] == settings.model_id


def test_throttling_is_retried_then_succeeds(settings: Settings) -> None:
    port = FakeBedrock(
        [client_error("ThrottlingException", "Retrieve"), fixture("retrieve_returns")],
        [client_error("ServiceUnavailableException"), fixture("converse_answer")],
    )
    delays: list[float] = []
    answer = answer_question("Return window?", port=port, settings=settings, sleep=delays.append)
    assert not answer.refused
    assert len(delays) == 2
    assert all(0 <= d <= 0.25 for d in delays)


def test_throttling_after_every_attempt_raises_throttled(settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [client_error("ThrottlingException")] * 3)
    with pytest.raises(ThrottledError):
        ask(port, settings)
    assert len(port.converse_calls) == 3


def test_non_retryable_error_is_not_retried(settings: Settings) -> None:
    port = FakeBedrock([client_error("AccessDeniedException", "Retrieve")])
    with pytest.raises(UpstreamError, match="AccessDeniedException"):
        ask(port, settings)
    assert len(port.retrieve_calls) == 1


def test_backoff_grows_exponentially() -> None:
    delays: list[float] = []
    calls = iter([client_error("ThrottlingException")] * 3 + [None])

    def flaky() -> str:
        error = next(calls)
        if error:
            raise error
        return "ok"

    assert call_with_retries(flaky, attempts=4, base_delay=1.0, sleep=delays.append) == "ok"
    assert delays[0] <= 1.0
    assert delays[1] <= 2.0
    assert delays[2] <= 4.0


@pytest.mark.parametrize("question", ["", "   ", "x" * 1001])
def test_invalid_questions_are_rejected_before_any_call(settings: Settings, question: str) -> None:
    port = FakeBedrock([])
    with pytest.raises(InvalidQuestionError):
        ask(port, settings, question)
    assert port.retrieve_calls == []


def test_context_over_budget_is_trimmed(settings: Settings) -> None:
    big = fixture("retrieve_returns")
    for result in big["retrievalResults"]:
        result["content"]["text"] = result["content"]["text"] * 200
    tight = Settings(**{**settings.__dict__, "max_context_tokens": 300})
    port = FakeBedrock([big], [fixture("converse_answer")])
    ask(port, tight)
    context = port.converse_calls[0]["messages"][0]["content"][0]["guardContent"]["text"]["text"]
    assert len(context) <= 300 * 4 + 100
