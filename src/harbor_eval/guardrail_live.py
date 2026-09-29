"""Live red-team run: send every case in data/fixtures/guardrail_cases.jsonl through ApplyGuardrail and compare the
action with `live_action`. Masking PII (ANONYMIZE) also counts as an intervention, so every PII case expects
INTERVENED. Makes AWS calls; `make test-live` runs it against the sandbox deployment only.

Each case goes through the guardrail in the block shape production sends: `apply_guardrail_request` takes the
`guardContent` blocks of the `Converse` request that `harbor_rag.prompt.build_converse_request` builds, with the case as
the question and one policy excerpt as the grounding source. A case the guardrail would not see in production (a
question qualified `query` only, for example) therefore fails here too. The case text is sent without the local
pre-filter: the run measures the guardrail as the control of record for what the pre-filter misses.

    python -m harbor_eval.guardrail_live --guardrail-id ID --guardrail-version 1 --profile NAME
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from harbor_eval import DATA
from harbor_rag.prompt import Source, build_converse_request

CASES = DATA / "fixtures" / "guardrail_cases.jsonl"
GROUNDING_SOURCE = Source(
    index=1,
    uri="s3://example-bucket/returns/returns-standard-window.md",
    title="Standard return window",
    doc_type="returns",
    text="Customers can return most items within 30 days of the delivery date. A receipt or order number is required.",
    score=1.0,
)


def load_cases() -> list[dict[str, Any]]:
    return [json.loads(line) for line in CASES.read_text(encoding="utf-8").splitlines() if line.strip()]


def apply_guardrail_request(text: str, *, guardrail_id: str, guardrail_version: str) -> dict[str, Any]:
    """An `ApplyGuardrail` request with the same guarded blocks and qualifiers as the production `Converse` request."""
    converse = build_converse_request(
        question=text,
        sources=[GROUNDING_SOURCE],
        model_id="unused",
        guardrail_id=guardrail_id,
        guardrail_version=guardrail_version,
        max_output_tokens=1,
    )
    content = [block["guardContent"] for block in converse["messages"][0]["content"] if "guardContent" in block]
    return {
        "guardrailIdentifier": guardrail_id,
        "guardrailVersion": guardrail_version,
        "source": "INPUT",
        "content": content,
    }


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
            **apply_guardrail_request(
                case["text"], guardrail_id=args.guardrail_id, guardrail_version=args.guardrail_version
            )
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
