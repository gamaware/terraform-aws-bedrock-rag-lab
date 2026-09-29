# Api stack: a private REST API (POST /ask, AWS_IAM auth) reachable only through an execute-api VPC endpoint, the
# ask function in private subnets with no route to the internet, VPC endpoints for Bedrock, an application
# inference profile for cost allocation, and the operations pieces (dashboard, alarms, budget).

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition
  region     = data.aws_region.current.region
  guardrail  = yamldecode(file("${path.module}/../../../config/guardrail.yaml"))

  # A cross-Region profile ("us." prefix) is copied from the system inference profile, and the function may call
  # the model in every Region of the profile. A single-Region model is copied from the foundation model.
  cross_region     = startswith(var.answer_model_id, "us.")
  base_model_id    = local.cross_region ? substr(var.answer_model_id, 3, -1) : var.answer_model_id
  model_source_arn = local.cross_region ? "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:inference-profile/${var.answer_model_id}" : "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.answer_model_id}"
  foundation_model_arns = local.cross_region ? [
    "arn:${local.partition}:bedrock:*::foundation-model/${local.base_model_id}",
    local.model_source_arn,
  ] : [local.model_source_arn]
}

resource "aws_kms_key" "api" {
  description             = "${var.name}: ask function environment and API, function and flow logs"
  enable_key_rotation     = true
  deletion_window_in_days = 30

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AccountAdministration"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "kms:*"
        Resource  = "*"
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${local.region}.amazonaws.com" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:*${var.name}*" }
        }
      },
    ]
  })
}

resource "aws_kms_alias" "api" {
  name          = "alias/${var.name}-api"
  target_key_id = aws_kms_key.api.key_id
}

# Tags on the profile carry into Cost Explorer, so answer tokens show up as their own cost line.
resource "aws_bedrock_inference_profile" "answers" {
  name = "${var.name}-answers"
  # The API accepts only letters, digits, ":" and "." with single separators: no parentheses or commas.
  description = "Answers for the Harbor Goods policy assistant using ${var.answer_model_id}"

  model_source {
    copy_from = local.model_source_arn
  }

  tags = {
    cost-allocation = "${var.name}-answers"
  }
}
