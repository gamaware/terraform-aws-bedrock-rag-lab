# Knowledge-base stack: S3 Vectors bucket and index, the Bedrock knowledge base over them, the S3 data source with
# fixed-size chunking, the guardrail (from config/guardrail.yaml) and the function that starts an ingestion job when
# a policy document changes.

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}
data "aws_region" "current" {}

locals {
  account_id          = data.aws_caller_identity.current.account_id
  partition           = data.aws_partition.current.partition
  region              = data.aws_region.current.region
  policies_bucket     = element(split(":::", var.policies_bucket_arn), 1)
  embedding_model_arn = "arn:${local.partition}:bedrock:${local.region}::foundation-model/${var.embedding_model_id}"
}

resource "aws_kms_key" "kb" {
  description             = "${var.name}: vectors, knowledge base, guardrail, ingestion function"
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
        Sid       = "S3VectorsIndexing"
        Effect    = "Allow"
        Principal = { Service = "indexing.s3vectors.amazonaws.com" }
        Action    = "kms:Decrypt"
        Resource  = "*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id }
          # The indexing service calls with the index ARN (bucket/<name>/index/<index>) as the source, so the
          # bucket ARN alone does not match; allow this bucket and anything under it only.
          ArnLike = { "aws:SourceArn" = [
            "arn:${local.partition}:s3vectors:${local.region}:${local.account_id}:bucket/${var.name}-vectors",
            "arn:${local.partition}:s3vectors:${local.region}:${local.account_id}:bucket/${var.name}-vectors/*",
          ] }
        }
      },
      {
        Sid       = "CloudWatchLogs"
        Effect    = "Allow"
        Principal = { Service = "logs.${local.region}.amazonaws.com" }
        Action    = ["kms:Encrypt", "kms:Decrypt", "kms:ReEncrypt*", "kms:GenerateDataKey*", "kms:Describe*"]
        Resource  = "*"
        Condition = {
          ArnLike = { "kms:EncryptionContext:aws:logs:arn" = "arn:${local.partition}:logs:${local.region}:${local.account_id}:log-group:/aws/lambda/${var.name}-*" }
        }
      },
    ]
  })
}

resource "aws_kms_alias" "kb" {
  name          = "alias/${var.name}-kb"
  target_key_id = aws_kms_key.kb.key_id
}

resource "aws_s3vectors_vector_bucket" "this" {
  vector_bucket_name = "${var.name}-vectors"
  force_destroy      = var.force_destroy

  encryption_configuration {
    sse_type    = "aws:kms"
    kms_key_arn = aws_kms_key.kb.arn
  }
}

resource "aws_s3vectors_index" "policies" {
  vector_bucket_name = aws_s3vectors_vector_bucket.this.vector_bucket_name
  index_name         = "policies"
  data_type          = "float32"
  dimension          = var.embedding_dimensions
  distance_metric    = "cosine"

  # The chunk text and the knowledge base's own metadata go in non-filterable keys: filterable metadata is capped
  # at 2 KB per vector, and only doc_type, title and doc_id (the sidecar attributes) need to be filterable.
  metadata_configuration {
    non_filterable_metadata_keys = ["AMAZON_BEDROCK_TEXT", "AMAZON_BEDROCK_METADATA"]
  }
}
