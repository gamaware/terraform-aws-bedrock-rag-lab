"""Runtime settings, read once from the environment Terraform sets on the function."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from harbor_rag.pii import PiiPattern, load_patterns

DOC_TYPES = ("returns", "warranty", "shipping", "supplier", "store-ops")


@dataclass(frozen=True)
class Settings:
    knowledge_base_id: str
    model_id: str
    guardrail_id: str
    guardrail_version: str
    number_of_results: int = 8
    max_sources: int = 3
    min_score: float = 0.35
    relative_floor: float = 0.85
    max_context_tokens: int = 2500
    max_output_tokens: int = 400
    max_question_chars: int = 1000
    pii_patterns: tuple[PiiPattern, ...] = ()

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> Settings:
        return cls(
            knowledge_base_id=env["KNOWLEDGE_BASE_ID"],
            model_id=env["MODEL_ID"],
            guardrail_id=env["GUARDRAIL_ID"],
            guardrail_version=env["GUARDRAIL_VERSION"],
            number_of_results=int(env.get("NUMBER_OF_RESULTS", "8")),
            max_sources=int(env.get("MAX_SOURCES", "3")),
            min_score=float(env.get("MIN_SCORE", "0.35")),
            relative_floor=float(env.get("RELATIVE_FLOOR", "0.85")),
            max_context_tokens=int(env.get("MAX_CONTEXT_TOKENS", "2500")),
            max_output_tokens=int(env.get("MAX_OUTPUT_TOKENS", "400")),
            pii_patterns=load_patterns(env.get("PII_PATTERNS", "")),
        )
