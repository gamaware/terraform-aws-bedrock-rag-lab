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

resource "aws_cloudwatch_log_group" "ask" {
  name              = "/aws/lambda/${var.name}-ask"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.api.arn
}

resource "aws_iam_role" "ask" {
  name = "${var.name}-ask"
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

# Network interfaces for a function in a VPC: the AWS managed policy maintained for exactly this purpose.
resource "aws_iam_role_policy_attachment" "ask_vpc" {
  role       = aws_iam_role.ask.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

# Scoped access: one knowledge base, one inference profile and its model, one guardrail, two keys, one log group.
resource "aws_iam_role_policy" "ask" {
  name = "ask"
  role = aws_iam_role.ask.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid      = "RetrieveFromOneKnowledgeBase"
        Effect   = "Allow"
        Action   = "bedrock:Retrieve"
        Resource = var.knowledge_base_arn
      },
      {
        Sid      = "AnswerThroughTheInferenceProfile"
        Effect   = "Allow"
        Action   = "bedrock:InvokeModel"
        Resource = concat([aws_bedrock_inference_profile.answers.arn], local.foundation_model_arns)
      },
      {
        Sid      = "EnforceThePinnedGuardrail"
        Effect   = "Allow"
        Action   = "bedrock:ApplyGuardrail"
        Resource = var.guardrail_arn
      },
      {
        Sid      = "DecryptEnvironmentAndGuardrail"
        Effect   = "Allow"
        Action   = "kms:Decrypt"
        Resource = [aws_kms_key.api.arn, var.kb_kms_key_arn]
      },
      {
        Sid      = "OwnLogGroup"
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.ask.arn}:*"
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

resource "aws_lambda_function" "ask" {
  #checkov:skip=CKV_AWS_116:Invoked synchronously by API Gateway; a dead-letter queue only applies to asynchronous invocations.
  #checkov:skip=CKV_AWS_272:Code signing needs a signing profile and pipeline; the package is built from this repository by Terraform and its hash is tracked in the plan.
  function_name                  = "${var.name}-ask"
  role                           = aws_iam_role.ask.arn
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  handler                        = "harbor_rag.handler.lambda_handler"
  filename                       = data.archive_file.lambda.output_path
  source_code_hash               = data.archive_file.lambda.output_base64sha256
  timeout                        = 29
  memory_size                    = 512
  reserved_concurrent_executions = var.reserved_concurrency
  kms_key_arn                    = aws_kms_key.api.arn

  vpc_config {
    subnet_ids         = aws_subnet.private[*].id
    security_group_ids = [aws_security_group.function.id]
  }

  environment {
    variables = {
      KNOWLEDGE_BASE_ID = var.knowledge_base_id
      MODEL_ID          = aws_bedrock_inference_profile.answers.arn
      GUARDRAIL_ID      = var.guardrail_id
      GUARDRAIL_VERSION = var.guardrail_version
      NUMBER_OF_RESULTS = tostring(var.retrieval.number_of_results)
      MAX_SOURCES       = tostring(var.retrieval.max_sources)
      MIN_SCORE         = tostring(var.retrieval.min_score)
      RELATIVE_FLOOR    = tostring(var.retrieval.relative_floor)
      PII_PATTERNS      = jsonencode(local.guardrail.prefilter)
    }
  }

  tracing_config {
    mode = "Active"
  }

  logging_config {
    log_format = "Text"
    log_group  = aws_cloudwatch_log_group.ask.name
  }

  depends_on = [aws_iam_role_policy.ask, aws_iam_role_policy_attachment.ask_vpc, aws_vpc_endpoint.interface]
}
