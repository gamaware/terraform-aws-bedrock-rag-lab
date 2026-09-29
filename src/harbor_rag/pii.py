"""Local PII pre-filter that mirrors the guardrail's sensitive-information policy.

The guardrail only sees what goes through `Converse`. The question also goes to `Retrieve`, where it is embedded, and
into the function's logs, so it is redacted here first. The patterns come from `config/guardrail.yaml` (key
`prefilter`) through the `PII_PATTERNS` environment variable that Terraform sets, so Terraform, this module and the
tests read one source.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PiiPattern:
    name: str
    regex: re.Pattern[str]


@dataclass(frozen=True)
class Redaction:
    text: str
    found: tuple[str, ...]


def load_patterns(raw: str) -> tuple[PiiPattern, ...]:
    """Parse `[{"name": ..., "pattern": ...}, ...]`. An invalid pattern raises, so a bad deploy fails at cold start."""
    items = json.loads(raw) if raw else []
    if not isinstance(items, list):
        raise ValueError("PII_PATTERNS must be a JSON list")
    patterns = []
    for item in items:
        name, pattern = item["name"], item["pattern"]
        if not re.fullmatch(r"[A-Z0-9_]+", name):
            raise ValueError(f"PII pattern name must be upper snake case: {name!r}")
        patterns.append(PiiPattern(name=name, regex=re.compile(pattern)))
    return tuple(patterns)


def redact(text: str, patterns: tuple[PiiPattern, ...]) -> Redaction:
    """Replace every match with `{NAME}`, the same placeholder style the guardrail uses when it anonymizes."""
    found: list[str] = []
    for pattern in patterns:
        text, count = pattern.regex.subn("{" + pattern.name + "}", text)
        if count:
            found.append(pattern.name)
    return Redaction(text=text, found=tuple(found))
