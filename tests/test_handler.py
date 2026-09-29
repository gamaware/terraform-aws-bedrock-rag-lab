from __future__ import annotations

import json

import pytest

from harbor_rag import handler
from harbor_rag.config import Settings
from tests.fakes import FakeBedrock, client_error, fixture


def event(body: object) -> dict:
    return {"body": body if isinstance(body, str) else json.dumps(body)}


def call(port: FakeBedrock, settings: Settings, body: object) -> tuple[int, dict, dict]:
    response = handler.handle(event(body), "req-1", port, settings)
    return response["statusCode"], json.loads(response["body"]), response["headers"]


def test_answer_is_returned_as_json(settings: Settings, capsys: pytest.CaptureFixture[str]) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_answer")])
    status, body, headers = call(port, settings, {"question": "Return window for jane@example.com?"})
    assert status == 200
    assert headers["Content-Type"] == "application/json"
    assert set(body) == {"answer", "citations", "guardrail", "refused", "reason", "usage", "redacted"}
    logs = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert logs[0]["event"] == "ask"
    assert "jane@example.com" not in json.dumps(logs)
    assert logs[0]["question"] == "Return window for {EMAIL}?"
    metrics = logs[1]
    assert metrics["_aws"]["CloudWatchMetrics"][0]["Namespace"] == handler.METRIC_NAMESPACE
    assert (metrics["InputTokens"], metrics["OutputTokens"], metrics["Refusals"]) == (412, 58, 0)


@pytest.mark.parametrize(
    "body",
    ["not json", {"question": 3}, ["question"], {}, {"question": "ok?", "doc_type": "hr"}, {"question": ""}],
)
def test_bad_requests_get_400(settings: Settings, body: object) -> None:
    status, payload, _ = call(FakeBedrock([]), settings, body)
    assert status == 400
    assert "error" in payload


def test_throttling_gets_503_with_retry_after(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("harbor_rag.service.time.sleep", lambda _: None)
    port = FakeBedrock([client_error("ThrottlingException", "Retrieve")] * 3)
    status, _, headers = call(port, settings, {"question": "Return window?"})
    assert status == 503
    assert headers["Retry-After"] == "2"


def test_upstream_errors_get_502_without_details(settings: Settings) -> None:
    port = FakeBedrock([client_error("AccessDeniedException", "Retrieve")])
    status, payload, _ = call(port, settings, {"question": "Return window?"})
    assert status == 502
    assert "AccessDenied" not in payload["error"]


def test_settings_come_from_the_environment(pii_json: str) -> None:
    env = {
        "KNOWLEDGE_BASE_ID": "KB1",
        "MODEL_ID": "m",
        "GUARDRAIL_ID": "g",
        "GUARDRAIL_VERSION": "2",
        "MIN_SCORE": "0.4",
        "PII_PATTERNS": pii_json,
    }
    s = Settings.from_env(env)
    assert (s.knowledge_base_id, s.guardrail_version, s.min_score, s.max_sources) == ("KB1", "2", 0.4, 3)
    assert {p.name for p in s.pii_patterns} >= {"EMAIL", "LOYALTY_NUMBER"}


def test_lambda_handler_wires_env_and_port(monkeypatch: pytest.MonkeyPatch, settings: Settings) -> None:
    port = FakeBedrock([fixture("retrieve_returns")], [fixture("converse_answer")])
    monkeypatch.setattr(handler, "_port", lambda: port)
    monkeypatch.setattr(handler, "_settings", lambda: settings)

    class Context:
        aws_request_id = "abc"

    response = handler.lambda_handler(event({"question": "Return window?"}), Context())
    assert response["statusCode"] == 200
