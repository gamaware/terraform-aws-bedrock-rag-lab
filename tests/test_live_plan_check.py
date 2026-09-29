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


# Fresh plans: `terraform show -json` of the data and api stacks planned against an empty account (tests/fixtures/plans,
# see the README there). Bucket, topic and endpoint IDs are unknown until apply, as they are in `make test-live`.
PLANS = Path(__file__).resolve().parent / "fixtures" / "plans"
LIVE_TAGS = {"Lab": "terraform-aws-bedrock-rag-lab", "Ephemeral": "true", "purpose": "portfolio-test", "run": "123456"}


def fresh(stack: str) -> dict[str, Any]:
    plan: dict[str, Any] = json.loads((PLANS / f"{stack}-fresh.json").read_text(encoding="utf-8"))
    return plan


def document(plan: dict[str, Any], name: str) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """The planned `after`, `after_unknown` and configuration expressions of data.aws_iam_policy_document.<name>."""
    address = f"data.aws_iam_policy_document.{name}"
    change = next(c for c in plan["resource_changes"] if c["address"] == address)["change"]
    config = next(r for r in plan["configuration"]["root_module"]["resources"] if r["address"] == address)
    return change["after"], change["after_unknown"], config["expressions"]


def statement(after: dict[str, Any], sid: str) -> int:
    return next(i for i, s in enumerate(after["statement"]) if s["sid"] == sid)


@pytest.mark.parametrize("stack", ["data", "api"])
def test_fresh_stack_plans_pass_with_computed_arns(stack: str) -> None:
    plan = fresh(stack)
    policies = [
        c
        for c in plan["resource_changes"]
        if c["type"] in check_live_plan.POLICY_ATTRIBUTES and c["change"]["after_unknown"].get("policy")
    ]
    assert policies, "the fixture must contain policies that are unknown before apply"
    assert check_live_plan.check(plan, LIVE_TAGS) == []


def test_fresh_plan_statements_are_still_checked() -> None:
    plan = fresh("data")
    after, _, _ = document(plan, "alerts")
    after["statement"][statement(after, "AlarmsAndBudgetsInThisAccount")]["principals"] = [
        {"type": "AWS", "identifiers": ["*"]}
    ]
    after["statement"][statement(after, "AlarmsAndBudgetsInThisAccount")]["condition"] = []
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_sns_topic_policy.alerts: statement AlarmsAndBudgetsInThisAccount allows everyone"
    ]


def test_an_unknown_principal_is_refused() -> None:
    plan = fresh("data")
    after, unknown, _ = document(plan, "access_logs")
    i = statement(after, "S3ServerAccessLogs")
    after["statement"][i]["principals"][0]["identifiers"] = [None]
    unknown["statement"][i]["principals"] = [{"identifiers": [True]}]
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_s3_bucket_policy.access_logs: statement S3ServerAccessLogs: principals unknown before apply"
    ]


def test_an_open_statement_narrowed_only_by_a_computed_resource_id_passes() -> None:
    """The API's deny statement is conditioned on the endpoint ID, which is unknown until apply: that still narrows."""
    plan = fresh("api")
    after, _, _ = document(plan, "api")
    deny = after["statement"][statement(after, "DenyOutsideTheVpcEndpoint")]
    deny["effect"] = "Allow"
    assert check_live_plan.check(plan, LIVE_TAGS) == []


def test_an_unknown_condition_value_from_a_data_source_is_refused() -> None:
    plan = fresh("api")
    after, _, config = document(plan, "api")
    i = statement(after, "DenyOutsideTheVpcEndpoint")
    config["statement"][i]["condition"][0]["values"] = {
        "references": ["data.aws_vpc_endpoint.other.id", "data.aws_vpc_endpoint.other"]
    }
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_api_gateway_rest_api_policy.this: statement DenyOutsideTheVpcEndpoint: "
        "condition value unknown before apply and not from a managed resource"
    ]


def test_an_unknown_policy_not_built_from_a_policy_document_is_refused() -> None:
    """jsonencode(...) with a computed ARN hides the whole policy, principals included: undecidable before apply."""
    plan = fresh("data")
    config = next(
        r for r in plan["configuration"]["root_module"]["resources"] if r["address"] == "aws_s3_bucket_policy.policies"
    )
    config["expressions"]["policy"] = {"references": ["aws_s3_bucket.policies.arn", "aws_s3_bucket.policies"]}
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_s3_bucket_policy.policies: policy unknown before apply and not built from one aws_iam_policy_document"
    ]


def test_a_document_that_merges_other_documents_is_refused() -> None:
    plan = fresh("data")
    _, unknown, _ = document(plan, "policies")
    unknown["source_policy_documents"] = True
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_s3_bucket_policy.policies: policy merges other documents into data.aws_iam_policy_document.policies; "
        "cannot check before apply"
    ]


def test_unknown_endpoint_ids_do_not_hide_a_regional_api() -> None:
    plan = fresh("api")
    api = next(c for c in plan["resource_changes"] if c["address"] == "aws_api_gateway_rest_api.this")
    assert api["change"]["after_unknown"]["endpoint_configuration"][0]["vpc_endpoint_ids"] is True
    api["change"]["after"]["endpoint_configuration"][0]["types"] = ["REGIONAL"]
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_api_gateway_rest_api.this: API endpoint type ['REGIONAL'] is not PRIVATE"
    ]


@pytest.mark.parametrize(
    ("condition", "public"),
    [
        ({"StringEquals": {"aws:username": "${aws:username}"}}, True),
        ({"StringLike": {"s3:prefix": ["home/${aws:userid}/*"]}}, True),
        ({"StringEquals": {"aws:SourceAccount": "111122223333", "aws:username": "${aws:username}"}}, False),
        ({"StringEquals": {"aws:SourceAccount": "111122223333"}}, False),
    ],
)
def test_a_policy_variable_is_not_a_concrete_restriction(condition: dict[str, Any], public: bool) -> None:
    policy = json.dumps(
        {"Statement": [{"Sid": "Open", "Effect": "Allow", "Principal": "*", "Action": "s3:*", "Condition": condition}]}
    )
    assert check_live_plan.public_statements(policy) == (["Open"] if public else [])


def test_a_policy_variable_in_a_fresh_plan_document_is_not_a_restriction() -> None:
    plan = fresh("data")
    after, _, _ = document(plan, "alerts")
    open_statement = after["statement"][statement(after, "AlarmsAndBudgetsInThisAccount")]
    open_statement["principals"] = [{"type": "*", "identifiers": ["*"]}]
    open_statement["condition"] = [{"test": "StringEquals", "variable": "aws:username", "values": ["&{aws:username}"]}]
    assert check_live_plan.check(plan, LIVE_TAGS) == [
        "aws_sns_topic_policy.alerts: statement AlarmsAndBudgetsInThisAccount allows everyone"
    ]


def test_allow_with_not_principal_is_refused() -> None:
    policy = json.dumps({"Statement": [{"Sid": "Np", "Effect": "Allow", "NotPrincipal": {"AWS": "x"}, "Action": "*"}]})
    assert check_live_plan.public_statements(policy) == ["Np"]
