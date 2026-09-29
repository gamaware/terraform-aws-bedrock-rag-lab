#!/usr/bin/env python3
"""Pre-flight for `make test-live`: refuse a Terraform plan that would create anything public or untagged.

    python3 scripts/check_live_plan.py plan.json [plan.json ...] --require-tag Ephemeral=true --require-tag run=123

Reads `terraform show -json` output and exits 1 with one line per violation. Unknown values count as violations: a
check that cannot be decided before apply is not a pass. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

FORBIDDEN_TYPES = {
    "aws_internet_gateway": "internet gateway",
    "aws_egress_only_internet_gateway": "egress-only internet gateway",
    "aws_nat_gateway": "NAT gateway",
    "aws_eip": "Elastic IP address",
    "aws_lambda_function_url": "Lambda function URL",
    "aws_apigatewayv2_api": "HTTP or WebSocket API (public by design)",
    "aws_cloudfront_distribution": "CloudFront distribution",
    "aws_s3_bucket_website_configuration": "S3 website",
    "aws_lb": "load balancer",
}
OPEN_CIDRS = {"0.0.0.0/0", "::/0"}
PUBLIC_ACCESS_FLAGS = ("block_public_acls", "block_public_policy", "ignore_public_acls", "restrict_public_buckets")
POLICY_ATTRIBUTES = {
    "aws_s3_bucket_policy": "policy",
    "aws_s3vectors_vector_bucket_policy": "policy",
    "aws_api_gateway_rest_api_policy": "policy",
    "aws_sns_topic_policy": "policy",
    "aws_sqs_queue_policy": "policy",
}


def created(plan: Mapping[str, Any]) -> Iterator[tuple[str, str, Mapping[str, Any], Mapping[str, Any]]]:
    for change in plan.get("resource_changes", []):
        if change.get("mode") != "managed":
            continue
        actions = change.get("change", {}).get("actions", [])
        if "create" in actions or "update" in actions:
            yield (
                change["address"],
                change["type"],
                change["change"].get("after") or {},
                change["change"].get("after_unknown") or {},
            )


def public_statements(policy_json: str) -> list[str]:
    """Allow statements open to everyone without a condition that narrows them."""
    found = []
    statements = json.loads(policy_json).get("Statement", [])
    for statement in statements if isinstance(statements, list) else [statements]:
        principal = statement.get("Principal")
        open_principal = principal == "*" or (isinstance(principal, dict) and principal.get("AWS") == "*")
        if statement.get("Effect") == "Allow" and open_principal and not statement.get("Condition"):
            found.append(str(statement.get("Sid", "unnamed")))
    return found


def check(plan: Mapping[str, Any], required_tags: Mapping[str, str]) -> list[str]:
    violations = []
    for address, rtype, after, unknown in created(plan):
        if rtype.startswith("aws_route53"):
            violations.append(f"{address}: Route 53 resources are not allowed in a live test")
        if rtype in FORBIDDEN_TYPES:
            violations.append(f"{address}: {FORBIDDEN_TYPES[rtype]} is not allowed in a live test")
        if rtype == "aws_api_gateway_rest_api":
            if unknown.get("endpoint_configuration"):
                violations.append(f"{address}: endpoint type unknown before apply")
            else:
                types = [t for c in after.get("endpoint_configuration") or [] for t in c.get("types", [])]
                if types != ["PRIVATE"]:
                    violations.append(f"{address}: API endpoint type {types or 'EDGE (default)'} is not PRIVATE")
        if rtype == "aws_subnet" and after.get("map_public_ip_on_launch"):
            violations.append(f"{address}: subnet assigns public IP addresses")
        if rtype == "aws_route" and after.get("destination_cidr_block") in OPEN_CIDRS:
            violations.append(f"{address}: default route")
        if rtype == "aws_route_table":
            if unknown.get("route"):
                violations.append(f"{address}: routes unknown before apply")
            for route in after.get("route") or []:
                if route.get("cidr_block") in OPEN_CIDRS or route.get("ipv6_cidr_block") in OPEN_CIDRS:
                    violations.append(f"{address}: default route")
        if rtype == "aws_vpc_security_group_ingress_rule" and (
            after.get("cidr_ipv4") in OPEN_CIDRS or after.get("cidr_ipv6") in OPEN_CIDRS
        ):
            violations.append(f"{address}: ingress open to the internet")
        if rtype == "aws_s3_bucket_public_access_block":
            off = [flag for flag in PUBLIC_ACCESS_FLAGS if after.get(flag) is not True]
            if off:
                violations.append(f"{address}: public access block not fully on ({', '.join(off)})")
        if rtype in POLICY_ATTRIBUTES:
            attribute = POLICY_ATTRIBUTES[rtype]
            if unknown.get(attribute):
                violations.append(f"{address}: policy unknown before apply")
            elif after.get(attribute):
                violations.extend(
                    f"{address}: statement {sid} allows everyone" for sid in public_statements(after[attribute])
                )
        if "tags_all" in after or "tags_all" in unknown:
            tags = after.get("tags_all") or {}
            missing = [f"{k}={v}" for k, v in required_tags.items() if tags.get(k) != v]
            if missing and not unknown.get("tags_all"):
                violations.append(f"{address}: missing tags {', '.join(missing)}")
    return violations


def parse_tags(values: list[str]) -> dict[str, str]:
    tags = {}
    for value in values:
        key, sep, tag_value = value.partition("=")
        if not sep or not key:
            raise argparse.ArgumentTypeError(f"--require-tag expects Key=value, got {value!r}")
        tags[key] = tag_value
    return tags


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("plans", nargs="+", type=Path)
    parser.add_argument("--require-tag", action="append", default=[], metavar="KEY=VALUE")
    args = parser.parse_args(argv)
    required = parse_tags(args.require_tag)
    violations = []
    for path in args.plans:
        violations.extend(f"{path.name}: {v}" for v in check(json.loads(path.read_text(encoding="utf-8")), required))
    for violation in violations:
        print(f"FAIL  {violation}")
    if violations:
        return 1
    print(f"pass  {len(args.plans)} plan(s): nothing public, every taggable resource tagged")
    return 0


if __name__ == "__main__":
    sys.exit(main())
