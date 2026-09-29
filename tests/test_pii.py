from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from harbor_rag.pii import PiiPattern, load_patterns, redact

CASES = [
    json.loads(line)
    for line in (Path(__file__).resolve().parents[1] / "data/fixtures/guardrail_cases.jsonl").read_text().splitlines()
]


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_prefilter_finds_exactly_the_expected_pii(case: dict[str, Any], patterns: tuple[PiiPattern, ...]) -> None:
    result = redact(str(case["text"]), patterns)
    assert sorted(result.found) == sorted(case["prefilter"])
    for name in result.found:
        assert "{" + name + "}" in result.text


def test_redaction_removes_the_value(patterns: tuple[PiiPattern, ...]) -> None:
    result = redact("card 4111-1111-1111-1111 and mail a@example.com", patterns)
    assert "4111" not in result.text
    assert "a@example.com" not in result.text


def test_empty_config_means_no_patterns() -> None:
    assert load_patterns("") == ()


def test_pattern_names_must_be_upper_snake_case() -> None:
    with pytest.raises(ValueError, match="upper snake case"):
        load_patterns(json.dumps([{"name": "email", "pattern": "x"}]))


def test_invalid_regex_fails_at_load() -> None:
    with pytest.raises(Exception, match=r"unterminated|missing"):
        load_patterns(json.dumps([{"name": "BAD", "pattern": "(abc"}]))


def test_config_must_be_a_list() -> None:
    with pytest.raises(ValueError, match="JSON list"):
        load_patterns(json.dumps({"name": "X"}))
