"""Lambda entry point for POST /ask behind the private REST API (AWS_IAM authorization).

Request:  {"question": "...", "doc_type": "returns"}   (doc_type optional; one of config.DOC_TYPES)
Response: {"answer", "citations", "guardrail", "refused", "reason", "usage", "redacted"}

Logs are JSON lines with the redacted question only, plus CloudWatch embedded-metric-format records for tokens,
latency, refusals and guardrail interventions.
"""

from __future__ import annotations

import json
import os
import time
from functools import cache
from typing import Any

from harbor_rag.aws import Boto3Bedrock
from harbor_rag.config import DOC_TYPES, Settings
from harbor_rag.pii import redact
from harbor_rag.port import BedrockPort
from harbor_rag.service import Answer, InvalidQuestionError, ThrottledError, UpstreamError, answer_question

METRIC_NAMESPACE = "HarborGoods/PolicyAssistant"


@cache
def _settings() -> Settings:
    return Settings.from_env(os.environ)


@cache
def _port() -> BedrockPort:
    return Boto3Bedrock()


def _response(status: int, body: dict[str, Any], headers: dict[str, str] | None = None) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json", **(headers or {})},
        "body": json.dumps(body),
    }


def _emit(answer: Answer, redacted_question: str, latency_ms: int, request_id: str) -> None:
    print(
        json.dumps(
            {
                "event": "ask",
                "request_id": request_id,
                "question": redacted_question,
                "reason": answer.reason,
                "guardrail": answer.guardrail["action"],
                "findings": answer.guardrail["findings"],
                "citations": [c["uri"] for c in answer.citations],
                "redacted": answer.redacted,
                "latency_ms": latency_ms,
            }
        )
    )
    print(
        json.dumps(
            {
                "_aws": {
                    "Timestamp": int(time.time() * 1000),
                    "CloudWatchMetrics": [
                        {
                            "Namespace": METRIC_NAMESPACE,
                            "Dimensions": [[]],
                            "Metrics": [
                                {"Name": "InputTokens", "Unit": "Count"},
                                {"Name": "OutputTokens", "Unit": "Count"},
                                {"Name": "Latency", "Unit": "Milliseconds"},
                                {"Name": "Refusals", "Unit": "Count"},
                                {"Name": "GuardrailInterventions", "Unit": "Count"},
                            ],
                        }
                    ],
                },
                "InputTokens": answer.usage.get("inputTokens", 0),
                "OutputTokens": answer.usage.get("outputTokens", 0),
                "Latency": latency_ms,
                "Refusals": int(answer.refused),
                "GuardrailInterventions": int(answer.guardrail["action"] == "INTERVENED"),
            }
        )
    )


def handle(event: dict[str, Any], request_id: str, port: BedrockPort, settings: Settings) -> dict[str, Any]:
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "body must be JSON"})
    if not isinstance(body, dict) or not isinstance(body.get("question"), str):
        return _response(400, {"error": "body must be an object with a string 'question'"})
    doc_type = body.get("doc_type")
    if doc_type is not None and doc_type not in DOC_TYPES:
        return _response(400, {"error": f"doc_type must be one of {', '.join(DOC_TYPES)}"})

    started = time.monotonic()
    try:
        answer = answer_question(body["question"], port=port, settings=settings, doc_type=doc_type)
    except InvalidQuestionError as error:
        return _response(400, {"error": str(error)})
    except ThrottledError:
        print(json.dumps({"event": "ask_throttled", "request_id": request_id}))
        return _response(503, {"error": "the assistant is busy, retry shortly"}, {"Retry-After": "2"})
    except UpstreamError as error:
        print(json.dumps({"event": "ask_upstream_error", "request_id": request_id, "code": str(error)}))
        return _response(502, {"error": "the assistant could not answer, retry or contact Store Support"})
    latency_ms = int((time.monotonic() - started) * 1000)
    _emit(answer, redact(body["question"], settings.pii_patterns).text, latency_ms, request_id)
    return _response(200, answer.to_dict())


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    return handle(event, getattr(context, "aws_request_id", "local"), _port(), _settings())
