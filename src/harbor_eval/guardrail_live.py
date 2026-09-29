"""Live red-team run: send every case in data/fixtures/guardrail_cases.jsonl through ApplyGuardrail and compare the
action with `live_action`. Masking PII (ANONYMIZE) also counts as an intervention, so every PII case expects
INTERVENED. Makes AWS calls; `make test-live` runs it against the sandbox deployment only.

    python -m harbor_eval.guardrail_live --guardrail-id ID --guardrail-version 1 --profile NAME
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from harbor_eval import DATA

CASES = DATA / "fixtures" / "guardrail_cases.jsonl"


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - live only
    import boto3  # live path only

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guardrail-id", required=True)
    parser.add_argument("--guardrail-version", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--region", default="us-east-1")
    args = parser.parse_args(argv)
    client = boto3.Session(profile_name=args.profile, region_name=args.region).client("bedrock-runtime")
    failures = 0
    for case in load_cases():
        response = client.apply_guardrail(
            guardrailIdentifier=args.guardrail_id,
            guardrailVersion=args.guardrail_version,
            source="INPUT",
            content=[{"text": {"text": case["text"]}}],
        )
        action = "INTERVENED" if response["action"] == "GUARDRAIL_INTERVENED" else "NONE"
        ok = action == case["live_action"]
        failures += not ok
        verdict = "pass" if ok else "FAIL"
        print(f"{verdict}  {case['id']} {case['category']:<14} expected {case['live_action']}, got {action}")
    print(f"{len(load_cases()) - failures} of {len(load_cases())} guardrail cases as expected")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
