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
  target          = aws_s3_bucket.policies
  override_during = plan
  values          = { id = "harbor-policy-assistant-policies-111122223333-us-east-1", arn = "arn:aws:s3:::harbor-policy-assistant-policies-111122223333-us-east-1" }
}

override_resource {
  target          = aws_s3_bucket.invocation_logs
  override_during = plan
  values          = { id = "harbor-policy-assistant-invocations-111122223333-us-east-1", arn = "arn:aws:s3:::harbor-policy-assistant-invocations-111122223333-us-east-1" }
}

override_resource {
  target          = aws_s3_bucket.access_logs
  override_during = plan
  values          = { id = "harbor-policy-assistant-access-logs-111122223333-us-east-1", arn = "arn:aws:s3:::harbor-policy-assistant-access-logs-111122223333-us-east-1" }
}

override_resource {
  target          = aws_kms_key.data
  override_during = plan
  values          = { arn = "arn:aws:kms:us-east-1:111122223333:key/1234abcd-12ab-34cd-56ef-1234567890ab" }
}

run "buckets_are_private_versioned_and_encrypted" {
  command = plan

  assert {
    condition = alltrue([for b in [aws_s3_bucket_public_access_block.policies, aws_s3_bucket_public_access_block.invocation_logs, aws_s3_bucket_public_access_block.access_logs] : (
      b.block_public_acls && b.block_public_policy && b.ignore_public_acls && b.restrict_public_buckets
    )])
    error_message = "Every bucket must block all public access."
  }

  assert {
    condition     = alltrue([for v in [aws_s3_bucket_versioning.policies, aws_s3_bucket_versioning.invocation_logs, aws_s3_bucket_versioning.access_logs] : v.versioning_configuration[0].status == "Enabled"])
    error_message = "Versioning must be on for every bucket."
  }

  assert {
    condition = alltrue([for e in [aws_s3_bucket_server_side_encryption_configuration.policies, aws_s3_bucket_server_side_encryption_configuration.invocation_logs] : (
      one(e.rule).apply_server_side_encryption_by_default[0].sse_algorithm == "aws:kms" &&
      one(e.rule).apply_server_side_encryption_by_default[0].kms_master_key_id == aws_kms_key.data.arn
    )])
    error_message = "Policy documents and invocation logs must use SSE-KMS with the stack's key."
  }

  assert {
    condition     = aws_kms_key.data.enable_key_rotation
    error_message = "KMS key rotation must be on."
  }

  assert {
    condition     = alltrue([for o in [aws_s3_bucket_ownership_controls.policies, aws_s3_bucket_ownership_controls.invocation_logs, aws_s3_bucket_ownership_controls.access_logs] : o.rule[0].object_ownership == "BucketOwnerEnforced"])
    error_message = "ACLs must be disabled on every bucket."
  }
}

run "every_bucket_policy_denies_plain_http" {
  command = plan

  assert {
    condition = alltrue([for p in [aws_s3_bucket_policy.policies, aws_s3_bucket_policy.invocation_logs, aws_s3_bucket_policy.access_logs] :
      anytrue([for s in jsondecode(p.policy).Statement :
        s.Effect == "Deny" && try(s.Condition.Bool["aws:SecureTransport"], "") == "false"
    ])])
    error_message = "Each bucket policy must deny requests without TLS."
  }

  assert {
    condition = alltrue([for s in jsondecode(aws_s3_bucket_policy.invocation_logs.policy).Statement :
      s.Effect == "Deny" || (s.Principal.Service == "bedrock.amazonaws.com" && s.Condition.StringEquals["aws:SourceAccount"] == "111122223333")
    ])
    error_message = "Only Bedrock in this account may write invocation logs."
  }
}

run "invocation_logging_and_ingestion_events_are_on" {
  command = plan

  assert {
    condition     = length(aws_bedrock_model_invocation_logging_configuration.this) == 1
    error_message = "Model invocation logging must be on by default."
  }

  assert {
    condition = (
      aws_bedrock_model_invocation_logging_configuration.this[0].logging_config[0].text_data_delivery_enabled &&
      aws_bedrock_model_invocation_logging_configuration.this[0].logging_config[0].s3_config[0].bucket_name == aws_s3_bucket.invocation_logs.id
    )
    error_message = "Text invocations must be delivered to the invocation-log bucket."
  }

  assert {
    condition     = aws_s3_bucket_notification.policies.eventbridge
    error_message = "The policy bucket must send events to EventBridge (the ingestion trigger)."
  }

  assert {
    condition     = aws_sns_topic.alerts.kms_master_key_id == aws_kms_key.data.arn
    error_message = "The alerts topic must be encrypted with the stack's key."
  }
}

run "invocation_logging_can_be_left_to_another_team" {
  command = plan

  variables {
    enable_invocation_logging = false
  }

  assert {
    condition     = length(aws_bedrock_model_invocation_logging_configuration.this) == 0
    error_message = "enable_invocation_logging = false must not touch the account setting."
  }
}

run "rejects_an_invalid_name" {
  command = plan

  variables {
    name = "Harbor_Goods"
  }

  expect_failures = [var.name]
}
