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
  target          = aws_s3vectors_index.policies
  override_during = plan
  values          = { index_arn = "arn:aws:s3vectors:us-east-1:111122223333:bucket/harbor-policy-assistant-vectors/index/policies" }
}

override_resource {
  target          = aws_kms_key.kb
  override_during = plan
  values          = { arn = "arn:aws:kms:us-east-1:111122223333:key/2234abcd-12ab-34cd-56ef-1234567890ab" }
}

override_resource {
  target          = aws_bedrockagent_knowledge_base.this
  override_during = plan
  values = {
    id  = "KBHARBOR01"
    arn = "arn:aws:bedrock:us-east-1:111122223333:knowledge-base/KBHARBOR01"
  }
}

override_resource {
  target          = aws_sqs_queue.ingest_dlq
  override_during = plan
  values          = { arn = "arn:aws:sqs:us-east-1:111122223333:harbor-policy-assistant-ingest-dlq" }
}

override_resource {
  target          = aws_cloudwatch_log_group.ingest
  override_during = plan
  values          = { arn = "arn:aws:logs:us-east-1:111122223333:log-group:/aws/lambda/harbor-policy-assistant-ingest" }
}

variables {
  policies_bucket_arn = "arn:aws:s3:::harbor-policy-assistant-policies-111122223333-us-east-1"
  data_kms_key_arn    = "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab"
  alarm_topic_arn     = "arn:aws:sns:us-east-1:111122223333:harbor-policy-assistant-alerts"
}

run "knowledge_base_stores_vectors_in_s3_vectors" {
  command = plan

  assert {
    condition     = aws_bedrockagent_knowledge_base.this.storage_configuration[0].type == "S3_VECTORS"
    error_message = "The knowledge base must use S3 Vectors (ADR 0002)."
  }

  assert {
    condition     = aws_bedrockagent_knowledge_base.this.storage_configuration[0].s3_vectors_configuration[0].index_arn == aws_s3vectors_index.policies.index_arn
    error_message = "The knowledge base must point at this stack's index."
  }

  assert {
    condition = (
      aws_s3vectors_index.policies.dimension == aws_bedrockagent_knowledge_base.this.knowledge_base_configuration[0].vector_knowledge_base_configuration[0].embedding_model_configuration[0].bedrock_embedding_model_configuration[0].dimensions &&
      aws_s3vectors_index.policies.distance_metric == "cosine" &&
      aws_s3vectors_index.policies.data_type == "float32"
    )
    error_message = "Index dimension, metric and type must match the embedding model output."
  }

  assert {
    condition     = toset(aws_s3vectors_index.policies.metadata_configuration[0].non_filterable_metadata_keys) == toset(["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"])
    error_message = "Chunk text and Bedrock metadata must be non-filterable (2 KB filterable limit)."
  }

  assert {
    condition = (
      aws_s3vectors_vector_bucket.this.encryption_configuration[0].sse_type == "aws:kms" &&
      aws_s3vectors_vector_bucket.this.encryption_configuration[0].kms_key_arn == aws_kms_key.kb.arn
    )
    error_message = "Vectors must be encrypted with the stack's KMS key."
  }
}

run "chunking_matches_the_offline_decision" {
  command = plan

  assert {
    condition = (
      aws_bedrockagent_data_source.policies.vector_ingestion_configuration[0].chunking_configuration[0].chunking_strategy == "FIXED_SIZE" &&
      aws_bedrockagent_data_source.policies.vector_ingestion_configuration[0].chunking_configuration[0].fixed_size_chunking_configuration[0].max_tokens == 100 &&
      aws_bedrockagent_data_source.policies.vector_ingestion_configuration[0].chunking_configuration[0].fixed_size_chunking_configuration[0].overlap_percentage == 20
    )
    error_message = "Chunking must be fixed-size 100 tokens with 20 percent overlap (ADR 0006, data/eval.yaml)."
  }

  assert {
    condition     = aws_bedrockagent_data_source.policies.server_side_encryption_configuration[0].kms_key_arn == aws_kms_key.kb.arn
    error_message = "Transient ingestion data must be encrypted with the stack's key."
  }
}

run "guardrail_is_built_from_the_policy_file" {
  command = plan

  assert {
    condition     = length(aws_bedrock_guardrail.this.topic_policy_config[0].topics_config) == length(local.guardrail.denied_topics)
    error_message = "Every denied topic in config/guardrail.yaml must reach the guardrail."
  }

  assert {
    condition = contains([for f in aws_bedrock_guardrail.this.content_policy_config[0].filters_config :
    "${f.type}:${f.input_strength}:${f.output_strength}"], "PROMPT_ATTACK:HIGH:NONE")
    error_message = "The prompt-attack filter must be HIGH on input."
  }

  assert {
    condition = contains([for e in aws_bedrock_guardrail.this.sensitive_information_policy_config[0].pii_entities_config :
    "${e.type}:${e.action}"], "CREDIT_DEBIT_CARD_NUMBER:BLOCK")
    error_message = "Card numbers must be blocked."
  }

  assert {
    condition = anytrue([for f in aws_bedrock_guardrail.this.contextual_grounding_policy_config[0].filters_config :
    f.type == "GROUNDING" && f.threshold >= 0.7])
    error_message = "The contextual grounding check must be on with a threshold of at least 0.7."
  }

  assert {
    condition     = aws_bedrock_guardrail.this.kms_key_arn == aws_kms_key.kb.arn
    error_message = "The guardrail must be encrypted with the stack's key."
  }
}

run "roles_are_scoped_to_named_resources" {
  command = plan

  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.kb.policy).Statement :
    !contains(flatten([s.Resource]), "*")])
    error_message = "The knowledge base role must not grant access to every resource."
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.kb.policy).Statement : s.Resource if s.Sid == "WriteAndQueryOneIndex"]) == aws_s3vectors_index.policies.index_arn
    error_message = "Vector access must be limited to the one index."
  }

  assert {
    condition     = one([for s in jsondecode(aws_iam_role_policy.kb.policy).Statement : s.Resource if s.Sid == "EmbedWithOneModel"]) == "arn:aws:bedrock:us-east-1::foundation-model/amazon.titan-embed-text-v2:0"
    error_message = "The knowledge base may only call the embedding model."
  }

  assert {
    condition = alltrue([for s in jsondecode(aws_iam_role_policy.ingest.policy).Statement :
    s.Sid == "Tracing" || !contains(flatten([s.Resource]), "*")])
    error_message = "Only the X-Ray statement may use a wildcard resource."
  }

  assert {
    condition     = jsondecode(aws_iam_role.kb.assume_role_policy).Statement[0].Condition.StringEquals["aws:SourceAccount"] == "111122223333"
    error_message = "Only Bedrock in this account may assume the knowledge base role."
  }
}

run "policy_changes_trigger_ingestion_with_retries_and_a_dead_letter_queue" {
  command = plan

  assert {
    condition     = jsondecode(aws_cloudwatch_event_rule.policy_changed.event_pattern).detail.bucket.name == ["harbor-policy-assistant-policies-111122223333-us-east-1"]
    error_message = "The rule must match the policy bucket only."
  }

  assert {
    condition     = contains(local.lambda_files, "${split(".", aws_lambda_function.ingest.handler)[1]}.py") && startswith(aws_lambda_function.ingest.handler, "harbor_rag.")
    error_message = "The handler must name a module that the package zip holds under harbor_rag/."
  }

  assert {
    condition     = aws_bedrock_guardrail_version.this.skip_destroy
    error_message = "Publishing a new guardrail version must keep the one the api stack still pins."
  }

  assert {
    condition     = aws_lambda_function.ingest.dead_letter_config[0].target_arn == aws_sqs_queue.ingest_dlq.arn
    error_message = "Failed ingestion triggers must land in the dead-letter queue."
  }

  assert {
    condition     = aws_lambda_function_event_invoke_config.ingest.maximum_retry_attempts == 2
    error_message = "A conflicting ingestion job must be retried."
  }

  assert {
    condition     = aws_cloudwatch_metric_alarm.ingest_dlq.alarm_actions == toset([var.alarm_topic_arn])
    error_message = "A dead-lettered trigger must alert."
  }
}

run "rejects_unsupported_embedding_dimensions" {
  command = plan

  variables {
    embedding_dimensions = 1536
  }

  expect_failures = [var.embedding_dimensions]
}
