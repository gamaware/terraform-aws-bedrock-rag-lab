# Bedrock model invocation logging: prompts, answers and token counts of every model call in this account and
# Region go to the KMS-encrypted invocation-log bucket. It is an account-level setting; turn it off with
# enable_invocation_logging = false where another team already owns it.

locals {
  invocation_log_prefix = "bedrock"
}

resource "aws_bedrock_model_invocation_logging_configuration" "this" {
  count = var.enable_invocation_logging ? 1 : 0

  logging_config {
    text_data_delivery_enabled      = true
    embedding_data_delivery_enabled = false
    image_data_delivery_enabled     = false
    video_data_delivery_enabled     = false

    s3_config {
      bucket_name = aws_s3_bucket.invocation_logs.id
      key_prefix  = local.invocation_log_prefix
    }
  }

  depends_on = [aws_s3_bucket_policy.invocation_logs]
}
