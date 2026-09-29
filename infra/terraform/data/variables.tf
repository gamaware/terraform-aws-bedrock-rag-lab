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

variable "enable_invocation_logging" {
  description = "Turn on Bedrock model invocation logging for the account and Region (an account-level setting)."
  type        = bool
  default     = true
}

variable "noncurrent_version_days" {
  description = "Days to keep previous versions of policy documents and log objects."
  type        = number
  default     = 90

  validation {
    condition     = var.noncurrent_version_days >= 1
    error_message = "noncurrent_version_days must be at least 1."
  }
}

variable "log_retention_days" {
  description = "Days to keep invocation logs and S3 access logs."
  type        = number
  default     = 365

  validation {
    condition     = var.log_retention_days >= 1
    error_message = "log_retention_days must be at least 1."
  }
}

variable "force_destroy" {
  description = "Allow destroying buckets that still hold objects. Only the live test sets this."
  type        = bool
  default     = false
}
