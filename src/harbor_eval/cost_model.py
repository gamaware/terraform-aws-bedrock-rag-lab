"""Cost per question and per month, from pinned prices (data/prices.yaml) and workload assumptions
(data/workload.yaml). Input tokens per question come from the offline evaluation, which builds prompts with the
production prompt code over the golden set.

    python -m harbor_eval.cost_model
"""

from __future__ import annotations

import math
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import yaml

from harbor_eval import DATA
from harbor_eval.evaluate import load_config, run_offline

HOURS_PER_MONTH = 730
MILLION = 1_000_000


def load_yaml(name: str) -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((DATA / name).read_text(encoding="utf-8"))
    return data


def text_units(chars: int) -> int:
    return max(1, math.ceil(chars / 1000))


@dataclass(frozen=True)
class QuestionCost:
    model: float
    embedding: float
    guardrail: float
    retrieval: float
    compute: float

    @property
    def total(self) -> float:
        return self.model + self.embedding + self.guardrail + self.retrieval + self.compute


def per_question(
    prices: Mapping[str, Any], workload: Mapping[str, Any], model_id: str, input_tokens: int
) -> QuestionCost:
    model_price = prices["models"][model_id]
    output_tokens = workload["output_tokens_per_answer"]
    model = (input_tokens * model_price["input"] + output_tokens * model_price["output"]) / MILLION
    embedding = workload["query_embedding_tokens"] * prices["embedding"]["amazon.titan-embed-text-v2:0"] / MILLION

    g = prices["guardrails"]
    per_assessment = (g["content_filters"] + g["denied_topics"] + g["sensitive_information"]) / 1000
    input_units = text_units(workload["question_chars"])
    output_units = text_units(workload["answer_chars"])
    # Grounding compares the answer with the sources and the question: count all three.
    grounding_units = text_units(input_tokens * 4 + workload["answer_chars"])
    guardrail = (input_units + output_units) * per_assessment + grounding_units * g["contextual_grounding"] / 1000

    corpus = workload["corpus"]
    vector_bytes = corpus["chunks"] * (corpus["embedding_dimensions"] * 4 + corpus["metadata_bytes_per_vector"])
    s3v = prices["s3_vectors"]
    retrieval = s3v["queries_per_million"] / MILLION + vector_bytes / 1e12 * s3v["query_tb_processed"]

    lam = prices["lambda"]
    compute = (
        workload["lambda_memory_gb"] * workload["lambda_seconds_per_question"] * lam["gb_second"]
        + lam["requests_per_million"] / MILLION
        + prices["api_gateway_rest"]["requests_per_million"] / MILLION
        + workload["logs_gb_per_1000_questions"] / 1000 * prices["cloudwatch"]["logs_ingest_gb"]
    )
    return QuestionCost(model, embedding, guardrail, retrieval, compute)


def fixed_monthly(prices: Mapping[str, Any], workload: Mapping[str, Any]) -> dict[str, float]:
    corpus = workload["corpus"]
    vector_gb = corpus["chunks"] * (corpus["embedding_dimensions"] * 4 + corpus["metadata_bytes_per_vector"]) / 1e9
    return {
        "VPC interface endpoints": workload["interface_endpoints"]
        * workload["availability_zones"]
        * HOURS_PER_MONTH
        * prices["vpc_interface_endpoint"]["hour_per_az"],
        "KMS keys": workload["kms_keys"] * prices["kms"]["key_month"],
        "CloudWatch dashboard and alarms": prices["cloudwatch"]["dashboard_month"]
        + workload["alarms"] * prices["cloudwatch"]["alarm_month"],
        "S3 Vectors storage": vector_gb * prices["s3_vectors"]["storage_gb_month"],
    }


def vector_store_floor(prices: Mapping[str, Any], workload: Mapping[str, Any], questions: int) -> dict[str, float]:
    """Monthly vector store cost for the production corpus at a question volume (storage plus capacity floor)."""
    corpus = workload["corpus"]
    vector_gb = corpus["chunks"] * (corpus["embedding_dimensions"] * 4 + corpus["metadata_bytes_per_vector"]) / 1e9
    s3v = prices["s3_vectors"]
    oss = prices["opensearch_serverless"]
    aurora = prices["aurora_serverless_v2"]
    ocu = workload["opensearch_serverless_min_ocu"]
    return {
        "S3 Vectors": vector_gb * s3v["storage_gb_month"] + questions * s3v["queries_per_million"] / MILLION,
        "OpenSearch Serverless (dev/test, 1 OCU)": ocu["dev_test"] * oss["ocu_hour"] * HOURS_PER_MONTH
        + vector_gb * oss["storage_gb_month"],
        "OpenSearch Serverless (production, 2 OCU)": ocu["production"] * oss["ocu_hour"] * HOURS_PER_MONTH
        + vector_gb * oss["storage_gb_month"],
        "Aurora PostgreSQL Serverless v2 with pgvector (0.5 ACU)": workload["aurora_min_acu"]
        * aurora["acu_hour"]
        * HOURS_PER_MONTH
        + vector_gb * aurora["storage_gb_month"],
    }


def build(input_tokens: int) -> dict[str, Any]:
    prices, workload = load_yaml("prices.yaml"), load_yaml("workload.yaml")
    per_model = {m: per_question(prices, workload, m, input_tokens) for m in prices["models"]}
    fixed = fixed_monthly(prices, workload)
    default = per_model[workload["default_model"]]
    monthly = {
        q: {
            "variable": default.total * q,
            "fixed": sum(fixed.values()),
            "total": default.total * q + sum(fixed.values()),
        }
        for q in workload["questions_per_month"]
    }
    stores = {q: vector_store_floor(prices, workload, q) for q in workload["questions_per_month"]}
    return {
        "input_tokens": input_tokens,
        "output_tokens": workload["output_tokens_per_answer"],
        "default_model": workload["default_model"],
        "per_model": per_model,
        "fixed": fixed,
        "monthly": monthly,
        "vector_stores": stores,
    }


def main() -> int:
    input_tokens = run_offline(load_config())["answers"]["mean_input_tokens"]
    result = build(input_tokens)
    print(
        f"input tokens per question (offline mean): {input_tokens}; output tokens (assumed): {result['output_tokens']}"
    )
    for model, cost in result["per_model"].items():
        print(f"{model:<45} USD {cost.total * 1000:7.3f} per 1,000 questions")
    for q, m in result["monthly"].items():
        print(f"{q:>7} questions/month: USD {m['total']:.2f} ({result['default_model']}, fixed {m['fixed']:.2f})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
