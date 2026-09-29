from __future__ import annotations

import pytest

from harbor_eval import cost_model
from harbor_eval.cost_model import build, fixed_monthly, load_yaml, per_question, text_units, vector_store_floor

PRICES = {
    "models": {"m": {"input": 1.0, "output": 2.0}},
    "embedding": {"amazon.titan-embed-text-v2:0": 0.02},
    "guardrails": {
        "content_filters": 0.15,
        "denied_topics": 0.15,
        "sensitive_information": 0.10,
        "contextual_grounding": 0.10,
    },
    "s3_vectors": {"storage_gb_month": 0.06, "put_gb": 0.2, "queries_per_million": 2.5, "query_tb_processed": 0.004},
    "lambda": {"gb_second": 0.0000166667, "requests_per_million": 0.2},
    "api_gateway_rest": {"requests_per_million": 3.5},
    "cloudwatch": {"logs_ingest_gb": 0.5, "dashboard_month": 3.0, "alarm_month": 0.1},
    "vpc_interface_endpoint": {"hour_per_az": 0.01},
    "kms": {"key_month": 1.0},
}
WORKLOAD = {
    "output_tokens_per_answer": 100,
    "answer_chars": 600,
    "question_chars": 120,
    "query_embedding_tokens": 30,
    "lambda_memory_gb": 0.5,
    "lambda_seconds_per_question": 2.0,
    "logs_gb_per_1000_questions": 0.01,
    "interface_endpoints": 3,
    "availability_zones": 2,
    "kms_keys": 3,
    "alarms": 5,
    "corpus": {"chunks": 1000, "embedding_dimensions": 1024, "metadata_bytes_per_vector": 1024},
}


def test_text_units_round_up_per_thousand_characters() -> None:
    assert [text_units(c) for c in (0, 1, 1000, 1001, 2500)] == [1, 1, 1, 2, 3]


def test_model_cost_is_tokens_times_price() -> None:
    cost = per_question(PRICES, WORKLOAD, "m", input_tokens=1000)
    assert cost.model == pytest.approx((1000 * 1.0 + 100 * 2.0) / 1_000_000)


def test_guardrail_counts_input_output_and_grounding_units() -> None:
    cost = per_question(PRICES, WORKLOAD, "m", input_tokens=500)
    # input 1 unit + output 1 unit at 0.40 per 1,000; grounding over 2,000 + 600 chars = 3 units at 0.10 per 1,000
    assert cost.guardrail == pytest.approx(2 * 0.40 / 1000 + 3 * 0.10 / 1000)


def test_total_is_the_sum_of_parts() -> None:
    c = per_question(PRICES, WORKLOAD, "m", input_tokens=400)
    assert c.total == pytest.approx(c.model + c.embedding + c.guardrail + c.retrieval + c.compute)


def test_fixed_costs() -> None:
    fixed = fixed_monthly(PRICES, WORKLOAD)
    assert fixed["VPC interface endpoints"] == pytest.approx(3 * 2 * 730 * 0.01)
    assert fixed["KMS keys"] == 3


def test_s3_vectors_has_the_lowest_floor_at_every_volume() -> None:
    prices, workload = load_yaml("prices.yaml"), load_yaml("workload.yaml")
    for questions in workload["questions_per_month"]:
        stores = vector_store_floor(prices, workload, questions)
        assert min(stores, key=lambda k: stores[k]) == "S3 Vectors"


def test_build_uses_the_pinned_files_and_the_default_model() -> None:
    result = build(input_tokens=300)
    assert result["default_model"] in result["per_model"]
    for questions, month in result["monthly"].items():
        assert month["total"] == pytest.approx(month["variable"] + month["fixed"])
        assert month["variable"] == pytest.approx(result["per_model"][result["default_model"]].total * questions)


def test_every_model_the_api_stack_allows_has_a_price() -> None:
    prices = load_yaml("prices.yaml")
    allowed = ["amazon.nova-lite-v1:0", "amazon.nova-micro-v1:0", "anthropic.claude-haiku-4-5-20251001-v1:0"]
    assert set(allowed) <= set(prices["models"])


def test_cli_prints_a_summary(capsys: pytest.CaptureFixture[str]) -> None:
    assert cost_model.main() == 0
    assert "per 1,000 questions" in capsys.readouterr().out
