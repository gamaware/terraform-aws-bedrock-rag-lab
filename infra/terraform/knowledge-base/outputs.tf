output "knowledge_base_id" {
  description = "Knowledge base ID (api stack input)."
  value       = aws_bedrockagent_knowledge_base.this.id
}

output "knowledge_base_arn" {
  description = "Knowledge base ARN (api stack input)."
  value       = aws_bedrockagent_knowledge_base.this.arn
}

output "data_source_id" {
  description = "Data source ID, for a manual StartIngestionJob."
  value       = aws_bedrockagent_data_source.policies.data_source_id
}

output "vector_index_arn" {
  description = "S3 Vectors index that holds the embeddings."
  value       = aws_s3vectors_index.policies.index_arn
}

output "guardrail_id" {
  description = "Guardrail ID (api stack input)."
  value       = aws_bedrock_guardrail.this.guardrail_id
}

output "guardrail_arn" {
  description = "Guardrail ARN (api stack input)."
  value       = aws_bedrock_guardrail.this.guardrail_arn
}

output "guardrail_version" {
  description = "Published guardrail version the api stack pins."
  value       = aws_bedrock_guardrail_version.this.version
}

output "kms_key_arn" {
  description = "KMS key for the vectors and the guardrail (the ask function needs Decrypt on it)."
  value       = aws_kms_key.kb.arn
}
