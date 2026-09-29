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

variable "knowledge_base_id" {
  description = "Knowledge base ID (knowledge-base stack output)."
  type        = string
}

variable "knowledge_base_arn" {
  description = "Knowledge base ARN (knowledge-base stack output)."
  type        = string
}

variable "guardrail_id" {
  description = "Guardrail ID (knowledge-base stack output)."
  type        = string
}

variable "guardrail_arn" {
  description = "Guardrail ARN (knowledge-base stack output)."
  type        = string
}

variable "guardrail_version" {
  description = "Published guardrail version to enforce. DRAFT is refused: the function must run a reviewed version."
  type        = string

  validation {
    condition     = can(regex("^[0-9]+$", var.guardrail_version))
    error_message = "guardrail_version must be a published version number, not DRAFT."
  }
}

variable "kb_kms_key_arn" {
  description = "KMS key of the knowledge-base stack (the guardrail is encrypted with it)."
  type        = string
}

variable "alarm_topic_arn" {
  description = "SNS topic for alarms and the budget (data stack output alerts_topic_arn)."
  type        = string
}

variable "answer_model_id" {
  description = "Model that writes the answers (ADR 0007). Cross-Region inference profiles start with \"us.\"."
  type        = string
  default     = "amazon.nova-lite-v1:0"

  validation {
    condition = contains([
      "amazon.nova-lite-v1:0",
      "amazon.nova-micro-v1:0",
      "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    ], var.answer_model_id)
    error_message = "answer_model_id must be one of the models evaluated in report/REPORT.md."
  }
}

variable "vpc_cidr" {
  description = "CIDR of the private VPC that holds the function and the interface endpoints."
  type        = string
  default     = "10.40.0.0/16"

  validation {
    condition     = can(cidrhost(var.vpc_cidr, 0))
    error_message = "vpc_cidr must be a valid IPv4 CIDR block."
  }
}

variable "availability_zone_ids" {
  description = "Two zone IDs (not names, which differ per account) where the Bedrock endpoint services are offered."
  type        = list(string)
  default     = ["use1-az1", "use1-az2"]

  validation {
    condition     = length(var.availability_zone_ids) == 2
    error_message = "availability_zone_ids must list exactly two zone IDs."
  }
}

variable "retrieval" {
  description = "Context selection for the ask function (see src/harbor_rag/prompt.py and docs/runbook.md)."
  type = object({
    number_of_results = optional(number, 8)
    max_sources       = optional(number, 3)
    min_score         = optional(number, 0.35)
    relative_floor    = optional(number, 0.85)
  })
  default = {}

  validation {
    condition = (
      var.retrieval.min_score >= 0 && var.retrieval.min_score < 1 &&
      var.retrieval.relative_floor > 0 && var.retrieval.relative_floor <= 1 &&
      var.retrieval.max_sources >= 1 && var.retrieval.max_sources <= var.retrieval.number_of_results
    )
    error_message = "min_score must be in [0, 1), relative_floor in (0, 1], and 1 <= max_sources <= number_of_results."
  }
}

variable "reserved_concurrency" {
  description = "Upper bound on concurrent answers, which also bounds the Bedrock spend rate."
  type        = number
  default     = 20
}

variable "api_throttle" {
  description = "Stage-wide API throttling."
  type = object({
    rate_limit  = number
    burst_limit = number
  })
  default = { rate_limit = 10, burst_limit = 20 }
}

variable "monthly_budget_usd" {
  description = "Monthly cost budget for resources tagged project = name. Alerts at 80 percent forecast and 100 percent actual."
  type        = number
  default     = 150
}

variable "manage_api_gateway_account" {
  description = "Set the account-level API Gateway CloudWatch role (needed once per account and Region for API logs)."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "Days to keep function, API and flow logs."
  type        = number
  default     = 365
}
