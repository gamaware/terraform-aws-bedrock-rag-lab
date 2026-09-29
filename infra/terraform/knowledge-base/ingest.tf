# S3 change -> EventBridge -> ingest function -> StartIngestionJob. Failed invocations (for example a job already
# running) are retried twice by Lambda and then land in the dead-letter queue, which alarms.

# The zip keeps the package directory (harbor_rag/*.py), so the handler path harbor_rag.<module>.lambda_handler and
# the package's absolute imports resolve in the Lambda runtime.
locals {
  lambda_source = "${path.module}/../../../src/harbor_rag"
  lambda_files  = fileset(local.lambda_source, "*.py")
}

data "archive_file" "lambda" {
  type        = "zip"
  output_path = "${path.module}/build/harbor_rag.zip"

  dynamic "source" {
    for_each = local.lambda_files
    content {
      content  = file("${local.lambda_source}/${source.value}")
      filename = "harbor_rag/${source.value}"
    }
  }
}

resource "aws_cloudwatch_log_group" "ingest" {
  name              = "/aws/lambda/${var.name}-ingest"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.kb.arn
}

resource "aws_sqs_queue" "ingest_dlq" {
  name                      = "${var.name}-ingest-dlq"
  kms_master_key_id         = aws_kms_key.kb.arn
  message_retention_seconds = 1209600
}

resource "aws_iam_role" "ingest" {
  name = "${var.name}-ingest"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "ingest" {
  name = "ingest"
  role = aws_iam_role.ingest.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "StartIngestionForOneKnowledgeBase"
        Effect   = "Allow"
        Action   = "bedrock:StartIngestionJob"
        Resource = aws_bedrockagent_knowledge_base.this.arn
      },
      {
        Sid      = "OwnLogGroup"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.ingest.arn}:*"
      },
      {
        Sid      = "DeadLetterQueue"
        Effect   = "Allow"
        Action   = "sqs:SendMessage"
        Resource = aws_sqs_queue.ingest_dlq.arn
      },
      {
        Sid      = "KeyForEnvironmentAndQueue"
        Effect   = "Allow"
        Action   = ["kms:Decrypt", "kms:GenerateDataKey"]
        Resource = aws_kms_key.kb.arn
      },
      {
        # X-Ray write actions do not support resource-level permissions.
        Sid      = "Tracing"
        Effect   = "Allow"
        Action   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords"]
        Resource = "*"
      },
    ]
  })
}

resource "aws_lambda_function" "ingest" {
  #checkov:skip=CKV_AWS_117:Calls only the Bedrock control plane (StartIngestionJob) and reads no data; a VPC would add an endpoint and nothing else.
  #checkov:skip=CKV_AWS_272:Code signing needs a signing profile and pipeline; the package is built from this repository by Terraform and its hash is tracked in the plan.
  function_name                  = "${var.name}-ingest"
  role                           = aws_iam_role.ingest.arn
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  handler                        = "harbor_rag.ingest.lambda_handler"
  filename                       = data.archive_file.lambda.output_path
  source_code_hash               = data.archive_file.lambda.output_base64sha256
  timeout                        = 30
  memory_size                    = 256
  reserved_concurrent_executions = 2
  kms_key_arn                    = aws_kms_key.kb.arn

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = aws_bedrockagent_knowledge_base.this.id
      DATA_SOURCE_ID    = aws_bedrockagent_data_source.policies.data_source_id
    }
  }

  dead_letter_config {
    target_arn = aws_sqs_queue.ingest_dlq.arn
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.ingest.name
  }

  depends_on = [aws_iam_role_policy.ingest]
}

resource "aws_lambda_function_event_invoke_config" "ingest" {
  function_name                = aws_lambda_function.ingest.function_name
  maximum_retry_attempts       = 2
  maximum_event_age_in_seconds = 3600
}

resource "aws_cloudwatch_event_rule" "policy_changed" {
  name        = "${var.name}-policy-changed"
  description = "A policy document was added, replaced or deleted"
  event_pattern = jsonencode({
    source        = ["aws.s3"]
    "detail-type" = ["Object Created", "Object Deleted"]
    detail        = { bucket = { name = [local.policies_bucket] } }
  })
}

resource "aws_cloudwatch_event_target" "ingest" {
  rule = aws_cloudwatch_event_rule.policy_changed.name
  arn  = aws_lambda_function.ingest.arn
}

resource "aws_lambda_permission" "events" {
  statement_id  = "AllowPolicyChangedRule"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "events.amazonaws.com"
  source_arn    = aws_cloudwatch_event_rule.policy_changed.arn
}

resource "aws_cloudwatch_metric_alarm" "ingest_dlq" {
  alarm_name          = "${var.name}-ingest-failed"
  alarm_description   = "A policy change was not ingested after retries. See docs/runbook.md, Re-ingest."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  dimensions          = { QueueName = aws_sqs_queue.ingest_dlq.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alarm_topic_arn]
}
