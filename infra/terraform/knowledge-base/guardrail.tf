# The guardrail policy is data: config/guardrail.yaml, shared with the ask function's PII pre-filter and the tests.
# A published version is pinned for the api stack; the working draft is never used by the function.

locals {
  guardrail_file = "${path.module}/../../../config/guardrail.yaml"
  guardrail      = yamldecode(file(local.guardrail_file))
}

resource "aws_bedrock_guardrail" "this" {
  name                      = "${var.name}-${local.guardrail.name}"
  description               = local.guardrail.description
  blocked_input_messaging   = local.guardrail.blocked_input_message
  blocked_outputs_messaging = local.guardrail.blocked_output_message
  kms_key_arn               = aws_kms_key.kb.arn

  content_policy_config {
    dynamic "filters_config" {
      for_each = local.guardrail.content_filters
      content {
        type            = filters_config.value.type
        input_strength  = filters_config.value.input
        output_strength = filters_config.value.output
      }
    }
  }

  topic_policy_config {
    dynamic "topics_config" {
      for_each = local.guardrail.denied_topics
      content {
        name       = topics_config.value.name
        definition = trimspace(topics_config.value.definition)
        examples   = topics_config.value.examples
        type       = "DENY"
      }
    }
  }

  sensitive_information_policy_config {
    dynamic "pii_entities_config" {
      for_each = local.guardrail.pii_entities
      content {
        type   = pii_entities_config.value.type
        action = pii_entities_config.value.action
      }
    }
    dynamic "regexes_config" {
      for_each = local.guardrail.pii_regexes
      content {
        name        = regexes_config.value.name
        description = regexes_config.value.description
        pattern     = regexes_config.value.pattern
        action      = regexes_config.value.action
      }
    }
  }

  contextual_grounding_policy_config {
    dynamic "filters_config" {
      for_each = local.guardrail.contextual_grounding
      content {
        type      = filters_config.value.type
        threshold = filters_config.value.threshold
      }
    }
  }
}

# A new version is published whenever the policy file changes; the description records which file content it holds.
resource "aws_bedrock_guardrail_version" "this" {
  guardrail_arn = aws_bedrock_guardrail.this.guardrail_arn
  description   = "config/guardrail.yaml sha256 ${substr(filesha256(local.guardrail_file), 0, 16)}"

  # Versions are immutable snapshots of the draft: any change to the guardrail publishes a new one. The previous
  # version is kept (skip_destroy), so the api stack keeps working until its pin moves; deleting the guardrail
  # deletes every version.
  skip_destroy = true

  lifecycle {
    replace_triggered_by = [aws_bedrock_guardrail.this]
  }
}
