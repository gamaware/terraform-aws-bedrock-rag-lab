"""POST /ask: redact, retrieve, select, answer with the guardrail, map citations.

Rules the tests hold this module to:

- The question is redacted before it reaches `Retrieve` or a log line.
- No relevant context means a refusal, and no model call.
- An answer without at least one valid citation is replaced by the refusal: the assistant never states a policy it
  cannot point to.
- A guardrail intervention returns the guardrail's message and its findings, never the blocked text.
- Citation excerpts are source text the guardrail never assessed (the sources are grounding-only), so they go through
  the same PII pre-filter as the question before they leave the function.
- Throttling and transient errors are retried with backoff; the retry policy lives here, not in botocore.
"""

from __future__ import annotations

import random
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from botocore.exceptions import ClientError

from harbor_rag.config import Settings
from harbor_rag.pii import PiiPattern, redact
from harbor_rag.port import BedrockPort
from harbor_rag.prompt import NO_ANSWER, Source, build_converse_request, fit_to_budget, select_sources

REFUSAL = (
    "I can't answer that from the Harbor Goods policy documents. "
    "Check with your store manager or open a Store Support case."
)
RETRYABLE_CODES = frozenset(
    {"ThrottlingException", "ServiceUnavailableException", "ModelNotReadyException", "InternalServerException"}
)
CITATION = re.compile(r"\[(\d+(?:\s*,\s*\d+)*)\]")
EXCERPT_CHARS = 240


class InvalidQuestionError(ValueError):
    """The caller sent something that is not a question this API answers (HTTP 400)."""


class ThrottledError(RuntimeError):
    """Bedrock kept throttling after every retry (HTTP 503 with Retry-After)."""


class UpstreamError(RuntimeError):
    """Bedrock failed in a way a retry does not fix (HTTP 502)."""


@dataclass
class Answer:
    answer: str
    citations: list[dict[str, Any]]
    guardrail: dict[str, Any]
    refused: bool
    reason: str
    usage: dict[str, int] = field(default_factory=dict)
    redacted: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def call_with_retries[T](
    fn: Callable[[], T], *, attempts: int = 3, base_delay: float = 0.25, sleep: Callable[[float], None] = time.sleep
) -> T:
    """Retry retryable Bedrock errors with full-jitter exponential backoff; re-raise anything else."""
    for attempt in range(1, attempts + 1):
        try:
            return fn()
        except ClientError as error:
            code = error.response.get("Error", {}).get("Code", "")
            if code not in RETRYABLE_CODES:
                raise UpstreamError(code or "ClientError") from error
            if attempt == attempts:
                raise ThrottledError(code) from error
            sleep(random.uniform(0, base_delay * 2 ** (attempt - 1)))  # jitter only; not a security use
    raise AssertionError("unreachable")  # pragma: no cover


def guardrail_verdict(response: Mapping[str, Any]) -> dict[str, Any]:
    """Summarize the guardrail trace: the action and the policies that fired, without the text they matched."""
    intervened = response.get("stopReason") == "guardrail_intervened"
    findings: list[str] = []
    trace = response.get("trace", {}).get("guardrail", {})
    assessments: list[Mapping[str, Any]] = list(trace.get("inputAssessment", {}).values())
    for per_guardrail in trace.get("outputAssessments", {}).values():
        assessments.extend(per_guardrail)
    for assessment in assessments:
        for topic in assessment.get("topicPolicy", {}).get("topics", []):
            findings.append(f"topic:{topic.get('name')}:{topic.get('action')}")
        for content_filter in assessment.get("contentPolicy", {}).get("filters", []):
            findings.append(f"content:{content_filter.get('type')}:{content_filter.get('action')}")
        for entity in assessment.get("sensitiveInformationPolicy", {}).get("piiEntities", []):
            findings.append(f"pii:{entity.get('type')}:{entity.get('action')}")
        for regex in assessment.get("sensitiveInformationPolicy", {}).get("regexes", []):
            findings.append(f"pii:{regex.get('name')}:{regex.get('action')}")
        for grounding in assessment.get("contextualGroundingPolicy", {}).get("filters", []):
            if grounding.get("action") == "BLOCKED":
                findings.append(f"grounding:{grounding.get('type')}:BLOCKED")
    return {"action": "INTERVENED" if intervened else "NONE", "findings": sorted(set(findings))}


def map_citations(text: str, sources: list[Source], patterns: tuple[PiiPattern, ...]) -> list[dict[str, Any]]:
    """The cited sources, each with a short excerpt redacted by the PII pre-filter.

    The excerpt is redacted before it is cut, so a value split by the cut cannot slip past a pattern.
    """
    by_index = {s.index: s for s in sources}
    cited: list[int] = []
    for match in CITATION.finditer(text):
        for raw in match.group(1).split(","):
            index = int(raw)
            if index in by_index and index not in cited:
                cited.append(index)
    return [
        {
            "index": i,
            "title": by_index[i].title,
            "uri": by_index[i].uri,
            "doc_type": by_index[i].doc_type,
            "excerpt": redact(by_index[i].text, patterns).text[:EXCERPT_CHARS],
        }
        for i in cited
    ]


def _output_text(response: Mapping[str, Any]) -> str:
    content = response.get("output", {}).get("message", {}).get("content", [])
    return "".join(str(block.get("text", "")) for block in content).strip()


def answer_question(
    question: str,
    *,
    port: BedrockPort,
    settings: Settings,
    doc_type: str | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> Answer:
    question = question.strip()
    if not question:
        raise InvalidQuestionError("question is empty")
    if len(question) > settings.max_question_chars:
        raise InvalidQuestionError(f"question is longer than {settings.max_question_chars} characters")

    redaction = redact(question, settings.pii_patterns)
    not_evaluated = {"action": "NOT_EVALUATED", "findings": []}

    retrieved = call_with_retries(
        lambda: port.retrieve(
            knowledge_base_id=settings.knowledge_base_id,
            query=redaction.text,
            number_of_results=settings.number_of_results,
            doc_type=doc_type,
        ),
        sleep=sleep,
    )
    sources = select_sources(
        retrieved.get("retrievalResults", []),
        max_sources=settings.max_sources,
        min_score=settings.min_score,
        relative_floor=settings.relative_floor,
    )
    sources = fit_to_budget(sources, settings.max_context_tokens)
    if not sources:
        return Answer(REFUSAL, [], not_evaluated, refused=True, reason="no_context", redacted=list(redaction.found))

    request = build_converse_request(
        question=redaction.text,
        sources=sources,
        model_id=settings.model_id,
        guardrail_id=settings.guardrail_id,
        guardrail_version=settings.guardrail_version,
        max_output_tokens=settings.max_output_tokens,
    )
    response = call_with_retries(lambda: port.converse(request), sleep=sleep)
    usage = {k: int(v) for k, v in response.get("usage", {}).items() if k in ("inputTokens", "outputTokens")}
    verdict = guardrail_verdict(response)
    text = _output_text(response)

    if verdict["action"] == "INTERVENED":
        return Answer(
            text or REFUSAL, [], verdict, refused=True, reason="guardrail", usage=usage, redacted=list(redaction.found)
        )
    if not text or text.startswith(NO_ANSWER):
        return Answer(
            REFUSAL, [], verdict, refused=True, reason="model_declined", usage=usage, redacted=list(redaction.found)
        )
    citations = map_citations(text, sources, settings.pii_patterns)
    if not citations:
        return Answer(
            REFUSAL, [], verdict, refused=True, reason="no_citation", usage=usage, redacted=list(redaction.found)
        )
    return Answer(
        text, citations, verdict, refused=False, reason="answered", usage=usage, redacted=list(redaction.found)
    )
