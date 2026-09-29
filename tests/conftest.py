from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from harbor_rag.config import Settings
from harbor_rag.pii import PiiPattern, load_patterns

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _no_aws(monkeypatch: pytest.MonkeyPatch) -> None:
    """Dummy credentials and region: nothing in the unit tests may reach AWS, and nothing can sign for it."""
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_PROFILE", raising=False)


@pytest.fixture(scope="session")
def guardrail() -> dict[str, Any]:
    data: dict[str, Any] = yaml.safe_load((ROOT / "config" / "guardrail.yaml").read_text(encoding="utf-8"))
    return data


@pytest.fixture(scope="session")
def pii_json(guardrail: dict[str, Any]) -> str:
    """What Terraform puts in PII_PATTERNS: jsonencode(local.guardrail.prefilter)."""
    return json.dumps(guardrail["prefilter"])


@pytest.fixture(scope="session")
def patterns(pii_json: str) -> tuple[PiiPattern, ...]:
    return load_patterns(pii_json)


@pytest.fixture
def settings(patterns: tuple[PiiPattern, ...]) -> Settings:
    return Settings(
        knowledge_base_id="KBHARBOR01",
        model_id="arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/hgpolicy01",
        guardrail_id="gr-harbor",
        guardrail_version="1",
        pii_patterns=patterns,
    )
