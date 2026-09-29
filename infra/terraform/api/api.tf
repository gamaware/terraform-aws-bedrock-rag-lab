# Private REST API. Three layers keep it private:
#   1. endpoint type PRIVATE: no public DNS name, reachable only through an execute-api interface endpoint;
#   2. resource policy: denies every call that does not come through this VPC's endpoint;
#   3. AWS_IAM authorization on the method: callers sign with SigV4 and need execute-api:Invoke.

resource "aws_api_gateway_rest_api" "this" {
  name        = var.name
  description = "Harbor Goods policy assistant (private)"

  endpoint_configuration {
    types            = ["PRIVATE"]
    vpc_endpoint_ids = [aws_vpc_endpoint.interface["execute-api"].id]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_rest_api_policy" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowSignedCallsFromThisAccount"
        Effect    = "Allow"
        Principal = { AWS = "arn:${local.partition}:iam::${local.account_id}:root" }
        Action    = "execute-api:Invoke"
        Resource  = "execute-api:/*"
      },
      {
        Sid       = "DenyOutsideTheVpcEndpoint"
        Effect    = "Deny"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "execute-api:/*"
        Condition = { StringNotEquals = { "aws:SourceVpce" = aws_vpc_endpoint.interface["execute-api"].id } }
      },
    ]
  })
}

resource "aws_api_gateway_resource" "ask" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "ask"
}

resource "aws_api_gateway_model" "ask" {
  rest_api_id  = aws_api_gateway_rest_api.this.id
  name         = "AskRequest"
  content_type = "application/json"
  schema = jsonencode({
    "$schema"            = "http://json-schema.org/draft-04/schema#"
    type                 = "object"
    required             = ["question"]
    additionalProperties = false
    properties = {
      question = { type = "string", minLength = 1, maxLength = 1000 }
      doc_type = { type = "string", enum = ["returns", "warranty", "shipping", "supplier", "store-ops"] }
    }
  })
}

resource "aws_api_gateway_request_validator" "body" {
  rest_api_id           = aws_api_gateway_rest_api.this.id
  name                  = "body"
  validate_request_body = true
}

resource "aws_api_gateway_method" "ask" {
  rest_api_id          = aws_api_gateway_rest_api.this.id
  resource_id          = aws_api_gateway_resource.ask.id
  http_method          = "POST"
  authorization        = "AWS_IAM"
  request_validator_id = aws_api_gateway_request_validator.body.id
  request_models       = { "application/json" = aws_api_gateway_model.ask.name }
}

resource "aws_api_gateway_integration" "ask" {
  rest_api_id             = aws_api_gateway_rest_api.this.id
  resource_id             = aws_api_gateway_resource.ask.id
  http_method             = aws_api_gateway_method.ask.http_method
  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = aws_lambda_function.ask.invoke_arn
  timeout_milliseconds    = 29000
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowPrivateApi"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ask.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/POST/ask"
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  triggers = {
    redeploy = sha1(jsonencode([
      aws_api_gateway_resource.ask.id,
      aws_api_gateway_method.ask,
      aws_api_gateway_integration.ask,
      aws_api_gateway_model.ask.schema,
      aws_api_gateway_rest_api_policy.this.policy,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/${var.name}-access"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.api.arn
}

resource "aws_api_gateway_stage" "v1" {
  #checkov:skip=CKV_AWS_120:Answers must not be cached: each call is evaluated by the guardrail and logged, and a cache would serve one caller's answer to another.
  #checkov:skip=CKV2_AWS_51:Callers authenticate with SigV4 (AWS_IAM); the backend is a Lambda proxy, so a client certificate for the backend adds nothing.
  #checkov:skip=CKV2_AWS_29:The API is PRIVATE, reachable only through the VPC endpoint with IAM auth; request validation and stage throttling cover the WAF use cases here.
  rest_api_id          = aws_api_gateway_rest_api.this.id
  deployment_id        = aws_api_gateway_deployment.this.id
  stage_name           = "v1"
  xray_tracing_enabled = true

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.api_access.arn
    format = jsonencode({
      requestId      = "$context.requestId"
      caller         = "$context.identity.caller"
      userArn        = "$context.identity.userArn"
      sourceVpce     = "$context.identity.vpceId"
      resourcePath   = "$context.resourcePath"
      status         = "$context.status"
      latencyMs      = "$context.responseLatency"
      integrationErr = "$context.integration.error"
    })
  }

  depends_on = [aws_api_gateway_account.this]
}

resource "aws_api_gateway_method_settings" "all" {
  #checkov:skip=CKV_AWS_225:Caching is off on purpose, see the stage.
  rest_api_id = aws_api_gateway_rest_api.this.id
  stage_name  = aws_api_gateway_stage.v1.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    logging_level          = "INFO"
    data_trace_enabled     = false
    caching_enabled        = false
    throttling_rate_limit  = var.api_throttle.rate_limit
    throttling_burst_limit = var.api_throttle.burst_limit
  }
}

# Account-level setting: the role API Gateway uses to write execution and access logs in this Region.
resource "aws_iam_role" "api_gateway_logs" {
  count = var.manage_api_gateway_account ? 1 : 0
  name  = "${var.name}-apigateway-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "apigateway.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "api_gateway_logs" {
  count      = var.manage_api_gateway_account ? 1 : 0
  role       = aws_iam_role.api_gateway_logs[0].name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AmazonAPIGatewayPushToCloudWatchLogs"
}

resource "aws_api_gateway_account" "this" {
  count               = var.manage_api_gateway_account ? 1 : 0
  cloudwatch_role_arn = aws_iam_role.api_gateway_logs[0].arn
}
