# Offline: the mocked provider never calls AWS and needs no credentials.
# Account 111122223333 is the AWS documentation example ID.
mock_provider "aws" {
  override_data {
    target = data.aws_caller_identity.current
    values = { account_id = "111122223333" }
  }
  override_data {
    target = data.aws_partition.current
    values = { partition = "aws" }
  }
  override_data {
    target = data.aws_region.current
    values = { region = "us-east-1" }
  }
}

override_resource {
  target          = aws_bedrock_inference_profile.answers
  override_during = plan
  values          = { arn = "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/hgpolicy0001" }
}

override_resource {
  target          = aws_kms_key.api
  override_during = plan
  values          = { arn = "arn:aws:kms:us-east-1:111122223333:key/3234abcd-12ab-34cd-56ef-1234567890ab" }
}

override_resource {
  target          = aws_cloudwatch_log_group.ask
  override_during = plan
  values          = { arn = "arn:aws:logs:us-east-1:111122223333:log-group:/aws/lambda/harbor-policy-assistant-ask" }
}

override_resource {
  target          = aws_vpc_endpoint.interface
  override_during = plan
  values          = { id = "vpce-0a1b2c3d4e5f60718" }
}

variables {
  knowledge_base_id  = "KBHARBOR01"
  knowledge_base_arn = "arn:aws:bedrock:us-east-1:111122223333:knowledge-base/KBHARBOR01"
  guardrail_id       = "abcd1234efgh"
  guardrail_arn      = "arn:aws:bedrock:us-east-1:111122223333:guardrail/abcd1234efgh"
  guardrail_version  = "1"
  kb_kms_key_arn     = "arn:aws:kms:us-east-1:111122223333:key/2234abcd-12ab-34cd-56ef-1234567890ab"
  alarm_topic_arn    = "arn:aws:sns:us-east-1:111122223333:harbor-policy-assistant-alerts"
}

run "api_is_private_with_iam_auth" {
  command = plan

  assert {
    condition     = tolist(aws_api_gateway_rest_api.this.endpoint_configuration[0].types) == tolist(["PRIVATE"])
    error_message = "The REST API must be PRIVATE."
  }

  assert {
    condition     = aws_api_gateway_method.ask.authorization == "AWS_IAM"
    error_message = "POST /ask must require SigV4 (AWS_IAM)."
  }

  assert {
    condition = anytrue([for s in data.aws_iam_policy_document.api.statement :
      s.effect == "Deny" && one(s.principals).type == "*" && anytrue([for c in s.condition :
        c.test == "StringNotEquals" && c.variable == "aws:SourceVpce" && tolist(c.values) == tolist(["vpce-0a1b2c3d4e5f60718"])
    ])])
    error_message = "The resource policy must deny calls that do not come through the VPC endpoint."
  }

  assert {
    condition = alltrue([for s in data.aws_iam_policy_document.api.statement :
      s.effect == "Deny" || (one(s.principals).type == "AWS" && tolist(one(s.principals).identifiers) == tolist(["arn:aws:iam::111122223333:root"]))
    ])
    error_message = "Only principals of this account may be allowed."
  }

  assert {
    condition     = aws_api_gateway_request_validator.body.validate_request_body && jsondecode(aws_api_gateway_model.ask.schema).properties.question.maxLength == 1000
    error_message = "The request body must be validated against the AskRequest model."
  }

  assert {
    condition     = aws_api_gateway_method_settings.all.settings[0].caching_enabled == false && aws_api_gateway_method_settings.all.settings[0].data_trace_enabled == false
    error_message = "No response caching and no full request/response logging (it would log questions before redaction)."
  }

  assert {
    condition     = aws_api_gateway_stage.v1.xray_tracing_enabled && length(aws_api_gateway_stage.v1.access_log_settings) == 1
    error_message = "The stage must trace and write access logs."
  }
}

run "network_has_no_path_to_the_internet" {
  command = plan

  assert {
    condition     = length(aws_route_table.private.route) == 0
    error_message = "The private route table must have no routes besides the implicit local one (no IGW, no NAT)."
  }

  assert {
    condition     = alltrue([for s in aws_subnet.private : !s.map_public_ip_on_launch])
    error_message = "Subnets must not assign public IP addresses."
  }

  assert {
    condition     = toset(keys(aws_vpc_endpoint.interface)) == toset(["bedrock-runtime", "bedrock-agent-runtime", "execute-api"])
    error_message = "The function reaches Bedrock only through interface endpoints."
  }

  assert {
    condition     = alltrue([for e in aws_vpc_endpoint.interface : e.private_dns_enabled && e.vpc_endpoint_type == "Interface"])
    error_message = "Endpoints must be interface endpoints with private DNS."
  }

  assert {
    condition     = aws_vpc_security_group_egress_rule.function_to_endpoints.from_port == 443 && aws_vpc_security_group_egress_rule.function_to_endpoints.cidr_ipv4 == null
    error_message = "The function may only send HTTPS to the endpoint security group."
  }

  assert {
    condition     = length(aws_subnet.private) == 2 && length(aws_lambda_function.ask.vpc_config) == 1
    error_message = "The function must run in the two private subnets."
  }
}

run "function_is_wired_to_the_pinned_guardrail_and_profile" {
  command = plan

  assert {
    condition = (
      aws_lambda_function.ask.environment[0].variables.GUARDRAIL_VERSION == "1" &&
      aws_lambda_function.ask.environment[0].variables.GUARDRAIL_ID == var.guardrail_id &&
      aws_lambda_function.ask.environment[0].variables.MODEL_ID == aws_bedrock_inference_profile.answers.arn
    )
    error_message = "The function must call the inference profile with the pinned guardrail version."
  }

  assert {
    condition     = jsondecode(aws_lambda_function.ask.environment[0].variables.PII_PATTERNS) == local.guardrail.prefilter
    error_message = "The PII pre-filter must come from config/guardrail.yaml."
  }

  assert {
    condition     = contains(local.lambda_files, "${split(".", aws_lambda_function.ask.handler)[1]}.py") && startswith(aws_lambda_function.ask.handler, "harbor_rag.")
    error_message = "The handler must name a module that the package zip holds under harbor_rag/."
  }

  assert {
    condition     = aws_lambda_function.ask.kms_key_arn == aws_kms_key.api.arn && aws_lambda_function.ask.tracing_config[0].mode == "Active"
    error_message = "Environment encrypted with the stack's key, tracing on."
  }

  assert {
    condition     = aws_bedrock_inference_profile.answers.model_source[0].copy_from == "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0"
    error_message = "The default profile must wrap Nova Lite (ADR 0007)."
  }

  assert {
    condition     = alltrue([for g in [aws_cloudwatch_log_group.ask, aws_cloudwatch_log_group.api_access, aws_cloudwatch_log_group.flow_logs] : g.kms_key_id == aws_kms_key.api.arn])
    error_message = "Every log group must be encrypted with the stack's key."
  }
}

run "function_role_is_scoped_to_named_resources" {
  command = plan

  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.ask.policy).Statement :
    s.Sid == "Tracing" || !contains(flatten([s.Resource]), "*")])
    error_message = "Only the X-Ray statement may use a wildcard resource."
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.ask.policy).Statement : s.Resource if s.Sid == "RetrieveFromOneKnowledgeBase"]) == var.knowledge_base_arn
    error_message = "Retrieve must be limited to one knowledge base."
  }

  assert {
    condition = toset(one([for s in jsondecode(aws_iam_role_policy.ask.policy).Statement : s.Resource if s.Sid == "AnswerThroughTheInferenceProfile"])) == toset([
      "arn:aws:bedrock:us-east-1:111122223333:application-inference-profile/hgpolicy0001",
      "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
    ])
    error_message = "InvokeModel must be limited to the profile and its model."
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.ask.policy).Statement : s.Resource if s.Sid == "EnforceThePinnedGuardrail"]) == var.guardrail_arn
    error_message = "ApplyGuardrail must be limited to the one guardrail."
  }
}

run "operations_alert_the_topic" {
  command = plan

  assert {
    condition     = length(aws_cloudwatch_metric_alarm.this) == 4 && alltrue([for a in aws_cloudwatch_metric_alarm.this : a.alarm_actions == toset([var.alarm_topic_arn])])
    error_message = "Every alarm must notify the alerts topic."
  }

  assert {
    condition     = length(aws_budgets_budget.monthly.notification) == 2 && aws_budgets_budget.monthly.limit_amount == "150"
    error_message = "The monthly budget must alert on forecast and actual spend."
  }

  assert {
    condition     = tolist([for f in aws_budgets_budget.monthly.cost_filter : f.values][0]) == tolist(["user:project$harbor-policy-assistant"])
    error_message = "The budget must filter on this deployment's project tag."
  }
}

run "cross_region_profile_allows_the_model_in_its_regions" {
  command = plan

  variables {
    answer_model_id = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
  }

  assert {
    condition     = aws_bedrock_inference_profile.answers.model_source[0].copy_from == "arn:aws:bedrock:us-east-1:111122223333:inference-profile/us.anthropic.claude-haiku-4-5-20251001-v1:0"
    error_message = "A cross-Region model must be copied from its system inference profile."
  }

  assert {
    condition     = contains(local.foundation_model_arns, "arn:aws:bedrock:*::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0")
    error_message = "The role must allow the model in each Region the profile routes to."
  }
}

run "refuses_the_draft_guardrail" {
  command = plan

  variables {
    guardrail_version = "DRAFT"
  }

  expect_failures = [var.guardrail_version]
}

run "refuses_a_model_that_was_not_evaluated" {
  command = plan

  variables {
    answer_model_id = "anthropic.claude-opus-4-1-20250805-v1:0"
  }

  expect_failures = [var.answer_model_id]
}

run "refuses_inconsistent_retrieval_settings" {
  command = plan

  variables {
    retrieval = { max_sources = 12, number_of_results = 8 }
  }

  expect_failures = [var.retrieval]
}
