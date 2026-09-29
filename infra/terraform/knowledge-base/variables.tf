variable "name" {
  description = "Name prefix for every resource (lower case, digits and hyphens)."
  type        = string
  default     = "harbor-policy-assistant"

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,30}$", var.name))
    error_message = "name must be 3 to 31 characters: lower case letters, digits and hyphens, starting with a letter."
  }
}

variable "region" {
  description = "AWS Region for every stack in this repository."
  type        = string
  default     = "us-east-1"
}

variable "tags" {
  description = "Extra tags for every resource."
  type        = map(string)
  default     = {}
}

variable "policies_bucket_arn" {
  description = "ARN of the policy document bucket (data stack output policies_bucket_arn)."
  type        = string

  validation {
    condition     = can(regex("^arn:aws[a-z-]*:s3:::[a-z0-9.-]{3,63}$", var.policies_bucket_arn))
    error_message = "policies_bucket_arn must be an S3 bucket ARN."
  }
}

variable "data_kms_key_arn" {
  description = "KMS key that encrypts the policy documents (data stack output kms_key_arn)."
  type        = string
}

variable "alarm_topic_arn" {
  description = "SNS topic for alarms (data stack output alerts_topic_arn)."
  type        = string
}

variable "embedding_model_id" {
  description = "Embedding model for the knowledge base."
  type        = string
  default     = "amazon.titan-embed-text-v2:0"
}

variable "embedding_dimensions" {
  description = "Vector size. Titan Text Embeddings V2 supports 256, 512 and 1024."
  type        = number
  default     = 1024

  validation {
    condition     = contains([256, 512, 1024], var.embedding_dimensions)
    error_message = "embedding_dimensions must be 256, 512 or 1024."
  }
}

variable "chunk_max_tokens" {
  description = "Fixed-size chunk length in tokens (ADR 0006: chosen from the offline chunking comparison)."
  type        = number
  default     = 100

  validation {
    condition     = var.chunk_max_tokens >= 20 && var.chunk_max_tokens <= 8192
    error_message = "chunk_max_tokens must be between 20 and 8192."
  }
}

variable "chunk_overlap_percentage" {
  description = "Overlap between consecutive fixed-size chunks, in percent."
  type        = number
  default     = 20

  validation {
    condition     = var.chunk_overlap_percentage >= 1 && var.chunk_overlap_percentage <= 99
    error_message = "chunk_overlap_percentage must be between 1 and 99."
  }
}

variable "log_retention_days" {
  description = "Days to keep the ingestion function's logs."
  type        = number
  default     = 365
}

variable "force_destroy" {
  description = "Allow destroying the vector bucket while it holds indexes. Only the live test sets this."
  type        = bool
  default     = false
}
