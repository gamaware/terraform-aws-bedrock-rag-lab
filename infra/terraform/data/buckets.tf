# Three buckets, all private, versioned and TLS-only:
#   policies        - the documents the knowledge base ingests (SSE-KMS); EventBridge notifications on
#   invocation_logs - Bedrock model invocation logs (SSE-KMS)
#   access_logs     - S3 server access logs of the other two (SSE-S3: S3 log delivery cannot write SSE-KMS)

locals {
  buckets = {
    policies        = aws_s3_bucket.policies
    invocation_logs = aws_s3_bucket.invocation_logs
    access_logs     = aws_s3_bucket.access_logs
  }
  logged_buckets = {
    policies        = aws_s3_bucket.policies
    invocation_logs = aws_s3_bucket.invocation_logs
  }
}

resource "aws_s3_bucket" "policies" {
  #checkov:skip=CKV_AWS_144:Cross-Region replication is out of scope; versioning covers accidental deletes and the documents are re-uploadable from the document management system.
  bucket        = "${var.name}-policies-${local.bucket_suffix}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket" "invocation_logs" {
  #checkov:skip=CKV_AWS_144:Cross-Region replication is out of scope for logs kept for investigation, not for recovery.
  #checkov:skip=CKV2_AWS_62:Nothing consumes events from the log bucket; notifications would only add cost.
  bucket        = "${var.name}-invocations-${local.bucket_suffix}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket" "access_logs" {
  #checkov:skip=CKV_AWS_144:Cross-Region replication is out of scope for access logs.
  #checkov:skip=CKV2_AWS_62:Nothing consumes events from the access-log bucket.
  #checkov:skip=CKV_AWS_18:This is the access-log target; logging it to itself would loop.
  #checkov:skip=CKV_AWS_145:S3 server access log delivery only supports SSE-S3 on the target bucket.
  bucket        = "${var.name}-access-logs-${local.bucket_suffix}"
  force_destroy = var.force_destroy
}

resource "aws_s3_bucket_ownership_controls" "policies" {
  bucket = aws_s3_bucket.policies.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "policies" {
  bucket                  = aws_s3_bucket.policies.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "policies" {
  bucket = aws_s3_bucket.policies.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "policies" {
  bucket = aws_s3_bucket.policies.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "policies" {
  bucket = aws_s3_bucket.policies.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "invocation_logs" {
  bucket = aws_s3_bucket.invocation_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "invocation_logs" {
  bucket                  = aws_s3_bucket.invocation_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "invocation_logs" {
  bucket = aws_s3_bucket.invocation_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "invocation_logs" {
  bucket = aws_s3_bucket.invocation_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = aws_kms_key.data.arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "invocation_logs" {
  bucket = aws_s3_bucket.invocation_logs.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.log_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_ownership_controls" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "access_logs" {
  bucket                  = aws_s3_bucket.access_logs.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  versioning_configuration {
    status = "Enabled"
  }
}

# S3 server access log delivery only writes to SSE-S3 buckets.
# trivy:ignore:AWS-0132
resource "aws_s3_bucket_server_side_encryption_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id

  rule {
    id     = "expire-old-versions"
    status = "Enabled"
    filter {}
    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_version_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "expire-logs"
    status = "Enabled"
    filter {}
    expiration {
      days = var.log_retention_days
    }
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

resource "aws_s3_bucket_logging" "this" {
  for_each      = local.logged_buckets
  bucket        = each.value.id
  target_bucket = aws_s3_bucket.access_logs.id
  target_prefix = "${each.key}/"
}

# The ingestion trigger in the knowledge-base stack listens for these events.
resource "aws_s3_bucket_notification" "policies" {
  bucket      = aws_s3_bucket.policies.id
  eventbridge = true
}

locals {
  tls_only = {
    for key, bucket in local.buckets : key => {
      Sid       = "TlsOnly"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [bucket.arn, "${bucket.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }
  }
}

resource "aws_s3_bucket_policy" "policies" {
  bucket = aws_s3_bucket.policies.id
  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [local.tls_only.policies]
  })
  depends_on = [aws_s3_bucket_public_access_block.policies, aws_s3_bucket_public_access_block.invocation_logs, aws_s3_bucket_public_access_block.access_logs]
}

resource "aws_s3_bucket_policy" "invocation_logs" {
  bucket = aws_s3_bucket.invocation_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.tls_only.invocation_logs,
      {
        Sid       = "BedrockInvocationLogDelivery"
        Effect    = "Allow"
        Principal = { Service = "bedrock.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.invocation_logs.arn}/${local.invocation_log_prefix}/AWSLogs/${local.account_id}/BedrockModelInvocationLogs/*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id }
          ArnLike      = { "aws:SourceArn" = "arn:${local.partition}:bedrock:${local.region}:${local.account_id}:*" }
        }
      },
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.policies, aws_s3_bucket_public_access_block.invocation_logs, aws_s3_bucket_public_access_block.access_logs]
}

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = aws_s3_bucket.access_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      local.tls_only.access_logs,
      {
        Sid       = "S3ServerAccessLogs"
        Effect    = "Allow"
        Principal = { Service = "logging.s3.amazonaws.com" }
        Action    = "s3:PutObject"
        Resource  = "${aws_s3_bucket.access_logs.arn}/*"
        Condition = {
          StringEquals = { "aws:SourceAccount" = local.account_id }
          ArnLike      = { "aws:SourceArn" = [aws_s3_bucket.policies.arn, aws_s3_bucket.invocation_logs.arn] }
        }
      },
    ]
  })
  depends_on = [aws_s3_bucket_public_access_block.policies, aws_s3_bucket_public_access_block.invocation_logs, aws_s3_bucket_public_access_block.access_logs]
}
