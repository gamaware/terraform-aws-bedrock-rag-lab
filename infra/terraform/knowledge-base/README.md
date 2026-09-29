# knowledge-base stack

The S3 Vectors bucket and index, the Bedrock knowledge base and its S3 data source, the guardrail built from
`config/guardrail.yaml` with a published version, and the function that starts an ingestion job when a policy
document changes. See [ADR 0002](../../../docs/adr/0002-s3-vectors-over-opensearch-serverless.md) and
[ADR 0005](../../../docs/adr/0005-guardrail-and-pii-prefilter.md).

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
| [aws_bedrock_guardrail.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail) | resource |
| [aws_bedrock_guardrail_version.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrock_guardrail_version) | resource |
| [aws_bedrockagent_data_source.policies](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_data_source) | resource |
| [aws_bedrockagent_knowledge_base.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/bedrockagent_knowledge_base) | resource |
| [aws_cloudwatch_event_rule.policy_changed](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_rule) | resource |
| [aws_cloudwatch_event_target.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_event_target) | resource |
| [aws_cloudwatch_log_group.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_log_group) | resource |
| [aws_cloudwatch_metric_alarm.ingest_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/cloudwatch_metric_alarm) | resource |
| [aws_iam_role.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role.kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role) | resource |
| [aws_iam_role_policy.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_iam_role_policy.kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/iam_role_policy) | resource |
| [aws_kms_alias.kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_alias) | resource |
| [aws_kms_key.kb](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/kms_key) | resource |
| [aws_lambda_function.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function) | resource |
| [aws_lambda_function_event_invoke_config.ingest](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_function_event_invoke_config) | resource |
| [aws_lambda_permission.events](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/lambda_permission) | resource |
| [aws_s3vectors_index.policies](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_index) | resource |
| [aws_s3vectors_vector_bucket.this](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/s3vectors_vector_bucket) | resource |
| [aws_sqs_queue.ingest_dlq](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/resources/sqs_queue) | resource |
| [archive_file.lambda](https://registry.terraform.io/providers/hashicorp/archive/latest/docs/data-sources/file) | data source |
| [aws_caller_identity.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/caller_identity) | data source |
| [aws_partition.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/partition) | data source |
| [aws_region.current](https://registry.terraform.io/providers/hashicorp/aws/latest/docs/data-sources/region) | data source |

## Inputs

| Name | Description | Type | Default | Required |
| ---- | ----------- | ---- | ------- | :------: |
| alarm\_topic\_arn | SNS topic for alarms (data stack output alerts\_topic\_arn). | `string` | n/a | yes |
| data\_kms\_key\_arn | KMS key that encrypts the policy documents (data stack output kms\_key\_arn). | `string` | n/a | yes |
| policies\_bucket\_arn | ARN of the policy document bucket (data stack output policies\_bucket\_arn). | `string` | n/a | yes |
| chunk\_max\_tokens | Fixed-size chunk length in tokens (ADR 0006: chosen from the offline chunking comparison). | `number` | `100` | no |
| chunk\_overlap\_percentage | Overlap between consecutive fixed-size chunks, in percent. | `number` | `20` | no |
| embedding\_dimensions | Vector size. Titan Text Embeddings V2 supports 256, 512 and 1024. | `number` | `1024` | no |
| embedding\_model\_id | Embedding model for the knowledge base. | `string` | `"amazon.titan-embed-text-v2:0"` | no |
| force\_destroy | Allow destroying the vector bucket while it holds indexes. Only the live test sets this. | `bool` | `false` | no |
| log\_retention\_days | Days to keep the ingestion function's logs. | `number` | `365` | no |
| name | Name prefix for every resource (lower case, digits and hyphens). | `string` | `"harbor-policy-assistant"` | no |
| region | AWS Region for every stack in this repository. | `string` | `"us-east-1"` | no |
| tags | Extra tags for every resource. | `map(string)` | `{}` | no |

## Outputs

| Name | Description |
| ---- | ----------- |
| data\_source\_id | Data source ID, for a manual StartIngestionJob. |
| guardrail\_arn | Guardrail ARN (api stack input). |
| guardrail\_id | Guardrail ID (api stack input). |
| guardrail\_version | Published guardrail version the api stack pins. |
| kms\_key\_arn | KMS key for the vectors and the guardrail (the ask function needs Decrypt on it). |
| knowledge\_base\_arn | Knowledge base ARN (api stack input). |
| knowledge\_base\_id | Knowledge base ID (api stack input). |
| vector\_index\_arn | S3 Vectors index that holds the embeddings. |
<!-- END_TF_DOCS -->
