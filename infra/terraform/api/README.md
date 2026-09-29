# api stack

The private VPC and its Bedrock and execute-api endpoints, the ask function, the private REST API (`POST /ask`,
`AWS_IAM`), the application inference profile, and the dashboard, alarms and budget. See
[ADR 0001](../../../docs/adr/0001-private-api-with-iam-auth.md) and
[ADR 0007](../../../docs/adr/0007-model-choice-and-inference-profile.md).

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
| ---- | ------- |
| terraform | >= 1.11.0, < 2.0.0 |
| archive | ~> 2.7 |
| aws | ~> 6.66 |

## Providers

| Name | Version |
| ---- | ------- |
| archive | 2.8.1 |
| aws | 6.66.0 |

## Resources

| Name | Type |
| ---- | ---- |
| [aws_api_gateway_account.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_account) | resource |
| [aws_api_gateway_deployment.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_deployment) | resource |
| [aws_api_gateway_integration.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_integration) | resource |
| [aws_api_gateway_method.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_method) | resource |
| [aws_api_gateway_method_settings.all](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_method_settings) | resource |
| [aws_api_gateway_model.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_model) | resource |
| [aws_api_gateway_request_validator.body](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_request_validator) | resource |
| [aws_api_gateway_resource.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_resource) | resource |
| [aws_api_gateway_rest_api.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_rest_api) | resource |
| [aws_api_gateway_rest_api_policy.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_rest_api_policy) | resource |
| [aws_api_gateway_stage.v1](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/api_gateway_stage) | resource |
| [aws_bedrock_inference_profile.answers](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_inference_profile) | resource |
| [aws_budgets_budget.monthly](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/budgets_budget) | resource |
| [aws_cloudwatch_dashboard.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_dashboard) | resource |
| [aws_cloudwatch_log_group.api_access](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_log_group.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_metric_alarm.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_default_security_group.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/default_security_group) | resource |
| [aws_flow_log.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/flow_log) | resource |
| [aws_iam_role.api_gateway_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.flow_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy_attachment.api_gateway_logs](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_iam_role_policy_attachment.ask_vpc](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy_attachment) | resource |
| [aws_kms_alias.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_lambda_function.ask](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lambda_permission.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [aws_route_table.private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table) | resource |
| [aws_route_table_association.private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/route_table_association) | resource |
| [aws_security_group.endpoints](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_security_group.function](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/security_group) | resource |
| [aws_subnet.private](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/subnet) | resource |
| [aws_vpc.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc) | resource |
| [aws_vpc_endpoint.interface](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_endpoint) | resource |
| [aws_vpc_security_group_egress_rule.function_to_endpoints](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_egress_rule) | resource |
| [aws_vpc_security_group_ingress_rule.endpoints_from_vpc](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/vpc_security_group_ingress_rule) | resource |
| [archive_file.lambda](https://registry.terraform.io/providers/hashicorp/archive/latest/docs/data-sources/file) | data source |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_iam_policy_document.api](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/iam_policy_document) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| alarm\_topic\_arn | SNS topic for alarms and the budget (data stack output alerts\_topic\_arn). | `string` | n/a | yes |
| guardrail\_arn | Guardrail ARN (knowledge-base stack output). | `string` | n/a | yes |
| guardrail\_id | Guardrail ID (knowledge-base stack output). | `string` | n/a | yes |
| guardrail\_version | Published guardrail version to enforce. DRAFT is refused: the function must run a reviewed version. | `string` | n/a | yes |
| kb\_kms\_key\_arn | KMS key of the knowledge-base stack (the guardrail is encrypted with it). | `string` | n/a | yes |
| knowledge\_base\_arn | Knowledge base ARN (knowledge-base stack output). | `string` | n/a | yes |
| knowledge\_base\_id | Knowledge base ID (knowledge-base stack output). | `string` | n/a | yes |
| answer\_model\_id | Model that writes the answers (ADR 0007). Cross-Region inference profiles start with "us.". | `string` | `"amazon.nova-lite-v1:0"` | no |
| api\_throttle | Stage-wide API throttling. | ```object({ rate_limit = number burst_limit = number })``` | ```{ "burst_limit": 20, "rate_limit": 10 }``` | no |
| availability\_zone\_ids | Two zone IDs (not names, which differ per account) where the Bedrock endpoint services are offered. | `list(string)` | ```[ "use1-az1", "use1-az2" ]``` | no |
| log\_retention\_days | Days to keep function, API and flow logs. | `number` | `365` | no |
| manage\_api\_gateway\_account | Set the account-level API Gateway CloudWatch role (needed once per account and Region for API logs). | `bool` | `true` | no |
| monthly\_budget\_usd | Monthly cost budget for resources tagged project = name. Alerts at 80 percent forecast and 100 percent actual. | `number` | `150` | no |
| name | Name prefix for every resource (lower case, digits and hyphens). | `string` | `"harbor-policy-assistant"` | no |
| region | AWS Region for every stack in this repository. | `string` | `"us-east-1"` | no |
| reserved\_concurrency | Upper bound on concurrent answers, which also bounds the Bedrock spend rate. | `number` | `20` | no |
| retrieval | Context selection for the ask function (see src/harbor\_rag/prompt.py and docs/runbook.md). | ```object({ number_of_results = optional(number, 8) max_sources = optional(number, 3) min_score = optional(number, 0.35) relative_floor = optional(number, 0.85) })``` | `{}` | no |
| tags | Extra tags for every resource. | `map(string)` | `{}` | no |
| vpc\_cidr | CIDR of the private VPC that holds the function and the interface endpoints. | `string` | `"10.40.0.0/16"` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| api\_id | REST API ID. |
| ask\_function\_name | Ask function name (the live test invokes it directly with the same event API Gateway sends). |
| ask\_url | POST URL, resolvable only inside the VPC (private DNS on the execute-api endpoint). |
| inference\_profile\_arn | Application inference profile the function calls; its tags drive cost allocation. |
| vpc\_id | Private VPC that holds the function and the endpoints. |
<!-- END_TF_DOCS -->
