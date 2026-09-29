output "kms_key_arn" {
  description = "KMS key for the policy documents, invocation logs and alerts topic."
  value       = aws_kms_key.data.arn
}

output "policies_bucket_name" {
  description = "Bucket the knowledge base ingests. Upload policy documents and their .metadata.json files here."
  value       = aws_s3_bucket.policies.id
}

output "policies_bucket_arn" {
  description = "ARN of the policy document bucket."
  value       = aws_s3_bucket.policies.arn
}

output "invocation_logs_bucket_name" {
  description = "Bucket that receives Bedrock model invocation logs."
  value       = aws_s3_bucket.invocation_logs.id
}

output "alerts_topic_arn" {
  description = "SNS topic for alarms and the budget."
  value       = aws_sns_topic.alerts.arn
}
