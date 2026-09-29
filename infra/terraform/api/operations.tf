locals {
  metric_namespace = "HarborGoods/PolicyAssistant"
}

resource "aws_cloudwatch_dashboard" "this" {
  dashboard_name = var.name
  dashboard_body = jsonencode({
    widgets = [
      {
        type = "metric", x = 0, y = 0, width = 12, height = 6
        properties = {
          title   = "Tokens per 5 minutes"
          region  = local.region
          stat    = "Sum"
          period  = 300
          metrics = [[local.metric_namespace, "InputTokens"], [local.metric_namespace, "OutputTokens"]]
        }
      },
      {
        type = "metric", x = 12, y = 0, width = 12, height = 6
        properties = {
          title  = "Answer latency (ms)"
          region = local.region
          period = 300
          metrics = [
            [local.metric_namespace, "Latency", { stat = "p50" }],
            [local.metric_namespace, "Latency", { stat = "p95" }],
          ]
        }
      },
      {
        type = "metric", x = 0, y = 6, width = 12, height = 6
        properties = {
          title   = "Refusals and guardrail interventions"
          region  = local.region
          stat    = "Sum"
          period  = 300
          metrics = [[local.metric_namespace, "Refusals"], [local.metric_namespace, "GuardrailInterventions"]]
        }
      },
      {
        type = "metric", x = 12, y = 6, width = 12, height = 6
        properties = {
          title  = "Function and API errors"
          region = local.region
          stat   = "Sum"
          period = 300
          metrics = [
            ["AWS/Lambda", "Errors", "FunctionName", aws_lambda_function.ask.function_name],
            ["AWS/Lambda", "Throttles", "FunctionName", aws_lambda_function.ask.function_name],
            ["AWS/ApiGateway", "5XXError", "ApiName", aws_api_gateway_rest_api.this.name, "Stage", "v1"],
            ["AWS/ApiGateway", "4XXError", "ApiName", aws_api_gateway_rest_api.this.name, "Stage", "v1"],
          ]
        }
      },
    ]
  })
}

locals {
  alarms = {
    function-errors = {
      description = "The ask function raised errors. See docs/runbook.md, Investigate a bad answer."
      namespace   = "AWS/Lambda"
      metric      = "Errors"
      dimensions  = { FunctionName = aws_lambda_function.ask.function_name }
      threshold   = 0
    }
    function-throttles = {
      description = "Reserved concurrency is exhausted; staff get 429 or 503."
      namespace   = "AWS/Lambda"
      metric      = "Throttles"
      dimensions  = { FunctionName = aws_lambda_function.ask.function_name }
      threshold   = 5
    }
    api-5xx = {
      description = "The API returned server errors (Bedrock throttling or failures)."
      namespace   = "AWS/ApiGateway"
      metric      = "5XXError"
      dimensions  = { ApiName = aws_api_gateway_rest_api.this.name, Stage = "v1" }
      threshold   = 5
    }
    guardrail-spike = {
      description = "Unusual number of guardrail interventions: misuse, a prompt-injection attempt, or a bad document."
      namespace   = local.metric_namespace
      metric      = "GuardrailInterventions"
      dimensions  = {}
      threshold   = 20
    }
  }
}

resource "aws_cloudwatch_metric_alarm" "this" {
  for_each            = local.alarms
  alarm_name          = "${var.name}-${each.key}"
  alarm_description   = each.value.description
  namespace           = each.value.namespace
  metric_name         = each.value.metric
  dimensions          = each.value.dimensions
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = each.value.threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [var.alarm_topic_arn]
}

resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Needs the "project" cost allocation tag activated in the billing console.
  cost_filter {
    name   = "TagKeyValue"
    values = [format("user:project$%s", var.name)]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [var.alarm_topic_arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [var.alarm_topic_arn]
  }
}
