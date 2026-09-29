"""scripts/check_live_plan.py: the pre-flight that stops a live test before anything public is applied."""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_live_plan.py"
spec = importlib.util.spec_from_file_location("check_live_plan", SCRIPT)
assert spec is not None
assert spec.loader is not None
check_live_plan = importlib.util.module_from_spec(spec)
spec.loader.exec_module(check_live_plan)

TAGS = {"Lab": "terraform-aws-bedrock-rag-lab", "Ephemeral": "true", "run": "123456"}


def change(address: str, after: dict[str, Any], unknown: dict[str, Any] | None = None) -> dict[str, Any]:
    rtype = address.split(".")[0]
    return {
        "address": address,
        "mode": "managed",
        "type": rtype,
        "change": {"actions": ["create"], "after": after, "after_unknown": unknown or {}},
    }


def good_plan() -> dict[str, Any]:
    deny_http = json.dumps(
        {
            "Statement": [
                {
                    "Sid": "TlsOnly",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "s3:*",
                    "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                }
            ]
        }
    )
    api_policy = json.dumps(
        {
            "Statement": [
                {
                    "Sid": "Allow",
                    "Effect": "Allow",
                    "Principal": {"AWS": "arn:aws:iam::111122223333:root"},
                    "Action": "execute-api:Invoke",
                },
                {
                    "Sid": "Deny",
                    "Effect": "Deny",
                    "Principal": "*",
                    "Action": "execute-api:Invoke",
                    "Condition": {"StringNotEquals": {"aws:SourceVpce": "vpce-1"}},
                },
            ]
        }
    )
    return {
        "resource_changes": [
            change(
                "aws_api_gateway_rest_api.this", {"endpoint_configuration": [{"types": ["PRIVATE"]}], "tags_all": TAGS}
            ),
            change("aws_api_gateway_rest_api_policy.this", {"policy": api_policy}),
            change("aws_subnet.private[0]", {"map_public_ip_on_launch": False, "tags_all": TAGS}),
            change("aws_route_table.private", {"route": [], "tags_all": TAGS}),
            change(
                "aws_s3_bucket_public_access_block.policies", dict.fromkeys(check_live_plan.PUBLIC_ACCESS_FLAGS, True)
            ),
            change("aws_s3_bucket_policy.policies", {"policy": deny_http}),
            change("aws_vpc_security_group_ingress_rule.endpoints_from_vpc", {"cidr_ipv4": "10.40.0.0/16"}),
            {
                "address": "data.aws_region.current",
                "mode": "data",
                "type": "aws_region",
                "change": {"actions": ["read"]},
            },
        ]
    }


def violations(plan: dict[str, Any]) -> list[str]:
    return check_live_plan.check(plan, TAGS)


def test_the_private_tagged_plan_passes() -> None:
    assert violations(good_plan()) == []


@pytest.mark.parametrize(
    ("address", "after", "expected"),
    [
        ("aws_internet_gateway.this", {}, "internet gateway"),
        ("aws_nat_gateway.this", {}, "NAT gateway"),
        ("aws_route53_record.api", {}, "Route 53"),
        ("aws_lambda_function_url.ask", {}, "function URL"),
        ("aws_route.default", {"destination_cidr_block": "0.0.0.0/0"}, "default route"),
        ("aws_vpc_security_group_ingress_rule.open", {"cidr_ipv4": "0.0.0.0/0"}, "open to the internet"),
    ],
)
def test_public_resources_are_refused(address: str, after: dict[str, Any], expected: str) -> None:
    plan = good_plan()
    plan["resource_changes"].append(change(address, after))
    found = violations(plan)
    assert len(found) == 1
    assert expected in found[0]


def edit(address: str, **after: Any) -> dict[str, Any]:
    plan = copy.deepcopy(good_plan())
    for c in plan["resource_changes"]:
        if c["address"] == address:
            c["change"]["after"].update(after)
    return plan


def test_a_regional_api_is_refused() -> None:
    plan = edit("aws_api_gateway_rest_api.this", endpoint_configuration=[{"types": ["REGIONAL"]}])
    assert "not PRIVATE" in violations(plan)[0]


def test_an_api_without_endpoint_configuration_is_edge_and_refused() -> None:
    plan = edit("aws_api_gateway_rest_api.this", endpoint_configuration=[])
    assert "EDGE" in violations(plan)[0]


def test_unknown_endpoint_type_is_not_a_pass() -> None:
    plan = good_plan()
    plan["resource_changes"][0]["change"]["after_unknown"] = {"endpoint_configuration": True}
    assert "unknown" in violations(plan)[0]


def test_public_subnet_and_default_route_in_a_table_are_refused() -> None:
    plan = edit("aws_subnet.private[0]", map_public_ip_on_launch=True)
    assert "public IP" in violations(plan)[0]
    plan = edit("aws_route_table.private", route=[{"cidr_block": "0.0.0.0/0", "gateway_id": "igw-1"}])
    assert "default route" in violations(plan)[0]


def test_public_access_block_must_be_fully_on() -> None:
    plan = edit("aws_s3_bucket_public_access_block.policies", restrict_public_buckets=False)
    assert "restrict_public_buckets" in violations(plan)[0]


def test_an_allow_everyone_policy_is_refused() -> None:
    policy = json.dumps({"Statement": [{"Sid": "Open", "Effect": "Allow", "Principal": "*", "Action": "s3:GetObject"}]})
    found = violations(edit("aws_s3_bucket_policy.policies", policy=policy))
    assert found == ["aws_s3_bucket_policy.policies: statement Open allows everyone"]


def test_a_conditioned_allow_everyone_statement_passes() -> None:
    policy = json.dumps(
        {
            "Statement": {
                "Effect": "Allow",
                "Principal": {"AWS": "*"},
                "Action": "sns:Publish",
                "Condition": {"StringEquals": {"aws:SourceAccount": "111122223333"}},
            }
        }
    )
    assert violations(edit("aws_s3_bucket_policy.policies", policy=policy)) == []


def test_missing_run_tags_are_refused() -> None:
    plan = edit("aws_subnet.private[0]", tags_all={"Lab": "terraform-aws-bedrock-rag-lab"})
    assert violations(plan) == ["aws_subnet.private[0]: missing tags Ephemeral=true, run=123456"]


def test_cli_exit_codes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(good_plan()))
    plan = good_plan()
    plan["resource_changes"].append(change("aws_nat_gateway.this", {}))
    bad.write_text(json.dumps(plan))
    tag_args = [a for k, v in TAGS.items() for a in ("--require-tag", f"{k}={v}")]
    assert check_live_plan.main([str(good), *tag_args]) == 0
    assert check_live_plan.main([str(bad), *tag_args]) == 1
    assert "FAIL  bad.json: aws_nat_gateway.this" in capsys.readouterr().out


def test_malformed_tag_argument_is_rejected() -> None:
    with pytest.raises(Exception, match="Key=value"):
        check_live_plan.parse_tags(["novalue"])
