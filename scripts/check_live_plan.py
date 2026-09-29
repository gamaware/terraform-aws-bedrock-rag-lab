#!/usr/bin/env python3
"""Pre-flight for `make test-live`: refuse a Terraform plan that would create anything public or untagged.

    python3 scripts/check_live_plan.py plan.json [plan.json ...] --require-tag Ephemeral=true --require-tag run=123

Reads `terraform show -json` output and exits 1 with one line per violation. Unknown values count as violations: a
check that cannot be decided before apply is not a pass. Standard library only.

One kind of unknown is decidable. In a fresh plan a resource policy that names a bucket, topic or endpoint is unknown
until apply, because those ARNs and IDs are computed. When the policy comes from an `aws_iam_policy_document` data
source, the plan still carries each statement's effect, principals and conditions; the only unknowns are values that
the configuration takes from managed resources. Such a policy is checked statement by statement. Anything else that is
unknown (an effect, a principal, a condition key, a value taken from a data source or a module) is still a violation.

A statement open to everyone counts as narrowed only by a condition with a concrete value. A policy variable such as
`${aws:username}` is not concrete: it matches whoever makes the request.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterator, Mapping, Sequence
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


POLICY_VARIABLE = re.compile(r"[$&]\{[^}]*\}")
DOCUMENT = "data.aws_iam_policy_document."
# `aws_vpc_endpoint.interface["execute-api"].id` -> `aws_vpc_endpoint.interface["execute-api"]`
REFERENCE_ROOT = re.compile(
    r"^(?:local|var|module|each|count|path|terraform|data\.[a-z0-9_]+|[a-z0-9_]+)"  # kind, or data source type
    r"\.[A-Za-z0-9_-]+(?:\[[^\]]*\])?"  # name and optional instance key
)
# Arguments of aws_iam_policy_document that pull in other policies; the plan cannot show what they contain.
MERGED_DOCUMENTS = ("source_json", "override_json", "source_policy_documents", "override_policy_documents")


def as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def concrete(value: Any) -> bool:
    """A condition value that restricts something: a known value that is not a policy variable."""
    return isinstance(value, str | int | float | bool) and not POLICY_VARIABLE.search(str(value))


def open_principal(principal: Any) -> bool:
    if principal == "*":
        return True
    return isinstance(principal, dict) and "*" in as_list(principal.get("AWS"))


def narrowing_condition(condition: Any) -> bool:
    """True when at least one condition value is concrete."""
    if not isinstance(condition, dict):
        return False
    return any(
        concrete(value)
        for keys in condition.values()
        if isinstance(keys, dict)
        for values in keys.values()
        for value in as_list(values)
    )


def public_statements(policy_json: str) -> list[str]:
    """Allow statements open to everyone without a condition that narrows them."""
    found = []
    statements = json.loads(policy_json).get("Statement", [])
    for statement in as_list(statements):
        if statement.get("Effect") != "Allow":
            continue
        everyone = open_principal(statement.get("Principal")) or "NotPrincipal" in statement
        if everyone and not narrowing_condition(statement.get("Condition")):
            found.append(str(statement.get("Sid", "unnamed")))
    return found


def base_address(address: str) -> str:
    """`aws_s3_bucket.logs["a"]` and `aws_s3_bucket.logs[0]` both come from the block `aws_s3_bucket.logs`."""
    return re.sub(r"\[[^\]]*\]$", "", address)


def unknown_leaves(unknown: Any) -> bool:
    if unknown is True:
        return True
    if isinstance(unknown, dict):
        return any(unknown_leaves(v) for v in unknown.values())
    if isinstance(unknown, list):
        return any(unknown_leaves(v) for v in unknown)
    return False


def index(values: Any, i: int) -> Any:
    return values[i] if isinstance(values, list) and i < len(values) else None


class Plan:
    """Lookups into one `terraform show -json` document."""

    def __init__(self, plan: Mapping[str, Any]) -> None:
        resources = plan.get("configuration", {}).get("root_module", {}).get("resources", [])
        self.config = {r["address"]: r for r in resources}
        self.changes = {c["address"]: c for c in plan.get("resource_changes", [])}

    def expression(self, address: str, attribute: str) -> Mapping[str, Any]:
        expression: Mapping[str, Any] = self.config.get(base_address(address), {}).get("expressions", {}).get(attribute)
        return expression or {}

    def from_resources(self, references: Sequence[str]) -> bool:
        """The unknown comes from managed resources: at least one resource reference, none to a data source or module.

        Locals and variables are known at plan time unless they themselves reference resources.
        """
        roots = {base_address(match.group(0)) for ref in references if (match := REFERENCE_ROOT.match(ref))}
        resources = {r for r in roots if self.config.get(r, {}).get("mode") == "managed"}
        others = {r for r in roots - resources if not r.startswith(("local.", "var."))}
        return bool(resources) and not others


def document_violations(address: str, plan: Plan, attribute: str) -> list[str]:
    """Check an unknown policy built from one aws_iam_policy_document, using the statements the plan does carry."""
    references = plan.expression(address, attribute).get("references", [])
    documents = {".".join(ref.split(".")[:3]) for ref in references}
    if len(documents) != 1 or not all(ref.startswith(DOCUMENT) for ref in references):
        return [f"{address}: policy unknown before apply and not built from one aws_iam_policy_document"]
    document = documents.pop()
    change = plan.changes.get(document, {}).get("change", {})
    after, unknown = change.get("after") or {}, change.get("after_unknown") or {}
    config = plan.config.get(document, {}).get("expressions", {})
    if not after or unknown.get("statement") is True or not isinstance(after.get("statement"), list):
        return [f"{address}: policy unknown before apply ({document} statements unknown)"]
    if any(after.get(arg) or unknown_leaves(unknown.get(arg)) for arg in MERGED_DOCUMENTS):
        return [f"{address}: policy merges other documents into {document}; cannot check before apply"]
    violations = []
    for i, statement in enumerate(after["statement"]):
        sid = statement.get("sid") or f"#{i + 1}"
        where = f"{address}: statement {sid}"
        s_unknown = index(unknown.get("statement"), i) or {}
        s_config = index(config.get("statement"), i)
        if s_config is None:
            violations.append(f"{where} has no matching block in the configuration (dynamic block?)")
            continue
        for field in ("sid", "effect", "actions", "not_actions", "principals", "not_principals"):
            if unknown_leaves(s_unknown.get(field)):
                violations.append(f"{where}: {field} unknown before apply")
        for field in ("resources", "not_resources"):
            if unknown_leaves(s_unknown.get(field)) and not plan.from_resources(
                s_config.get(field, {}).get("references", [])
            ):
                violations.append(f"{where}: {field} unknown before apply and not from a managed resource")
        narrowed = False
        # Condition blocks are a set: the plan orders them by value, so match them to the configuration by key.
        condition_config = {
            (c.get("test", {}).get("constant_value"), c.get("variable", {}).get("constant_value")): c.get("values", {})
            for c in s_config.get("condition", [])
        }
        for j, condition in enumerate(statement.get("condition") or []):
            c_unknown = index(s_unknown.get("condition"), j) or {}
            if unknown_leaves(c_unknown.get("test")) or unknown_leaves(c_unknown.get("variable")):
                violations.append(f"{where}: condition key unknown before apply")
                continue
            values, values_unknown = as_list(condition.get("values")), c_unknown.get("values")
            if values_unknown is True:
                values, values_unknown = [None], [True]
            for k, value in enumerate(values):
                if index(values_unknown, k) is not True:
                    narrowed = narrowed or concrete(value)
                    continue
                expression = condition_config.get((condition.get("test"), condition.get("variable")), {})
                if plan.from_resources(expression.get("references", [])):
                    narrowed = True
                else:
                    violations.append(f"{where}: condition value unknown before apply and not from a managed resource")
        effect = statement.get("effect") or "Allow"
        everyone = bool(statement.get("not_principals")) or any(
            p.get("type") == "*" or (p.get("type") == "AWS" and "*" in as_list(p.get("identifiers")))
            for p in statement.get("principals") or []
        )
        if effect == "Allow" and everyone and not narrowed:
            violations.append(f"{where} allows everyone")
    return violations


def check(plan: Mapping[str, Any], required_tags: Mapping[str, str]) -> list[str]:
    violations = []
    lookups = Plan(plan)
    for address, rtype, after, unknown in created(plan):
        if rtype.startswith("aws_route53"):
            violations.append(f"{address}: Route 53 resources are not allowed in a live test")
        if rtype in FORBIDDEN_TYPES:
            violations.append(f"{address}: {FORBIDDEN_TYPES[rtype]} is not allowed in a live test")
        if rtype == "aws_api_gateway_rest_api":
            endpoint_unknown = unknown.get("endpoint_configuration")
            # The endpoint IDs are computed in a fresh plan; only the endpoint types decide whether the API is private.
            if endpoint_unknown is True or any(unknown_leaves(c.get("types")) for c in as_list(endpoint_unknown)):
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
                violations.extend(document_violations(address, lookups, attribute))
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
