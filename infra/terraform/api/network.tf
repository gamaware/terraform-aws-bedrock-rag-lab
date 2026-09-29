# Private-only network: two private subnets, no internet gateway, no NAT gateway, no public subnet. The function
# reaches Bedrock through interface endpoints; staff reach the API through the execute-api endpoint.

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true
  tags                 = { Name = var.name }
}

resource "aws_default_security_group" "this" {
  vpc_id = aws_vpc.this.id
  tags   = { Name = "${var.name}-default-unused" }
}

resource "aws_subnet" "private" {
  count                   = length(var.availability_zone_ids)
  vpc_id                  = aws_vpc.this.id
  availability_zone_id    = var.availability_zone_ids[count.index]
  cidr_block              = cidrsubnet(var.vpc_cidr, 8, count.index)
  map_public_ip_on_launch = false
  tags                    = { Name = "${var.name}-private-${var.availability_zone_ids[count.index]}" }
}

resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id
  # Explicitly empty: only the implicit local route. No internet gateway, no NAT gateway.
  route = []
  tags  = { Name = "${var.name}-private" }
}

resource "aws_route_table_association" "private" {
  count          = length(aws_subnet.private)
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_security_group" "function" {
  name        = "${var.name}-ask-function"
  description = "Ask function: HTTPS to the VPC endpoints only"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_egress_rule" "function_to_endpoints" {
  security_group_id            = aws_security_group.function.id
  description                  = "HTTPS to the Bedrock interface endpoints"
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
  referenced_security_group_id = aws_security_group.endpoints.id
}

resource "aws_security_group" "endpoints" {
  name        = "${var.name}-endpoints"
  description = "Interface endpoints: HTTPS from inside the VPC"
  vpc_id      = aws_vpc.this.id
}

resource "aws_vpc_security_group_ingress_rule" "endpoints_from_vpc" {
  security_group_id = aws_security_group.endpoints.id
  description       = "HTTPS from the VPC (the function, and staff clients routed into the VPC)"
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
  cidr_ipv4         = var.vpc_cidr
}

locals {
  endpoint_policies = {
    "bedrock-runtime" = {
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = ["bedrock:InvokeModel", "bedrock:ApplyGuardrail"]
        Resource  = concat([aws_bedrock_inference_profile.answers.arn, var.guardrail_arn], local.foundation_model_arns)
        Condition = { StringEquals = { "aws:PrincipalAccount" = local.account_id } }
      }]
    }
    "bedrock-agent-runtime" = {
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = "bedrock:Retrieve"
        Resource  = var.knowledge_base_arn
        Condition = { StringEquals = { "aws:PrincipalAccount" = local.account_id } }
      }]
    }
    "execute-api" = {
      Version = "2012-10-17"
      Statement = [{
        Effect    = "Allow"
        Principal = "*"
        Action    = "execute-api:Invoke"
        Resource  = "arn:${local.partition}:execute-api:${local.region}:${local.account_id}:*/*"
        Condition = { StringEquals = { "aws:PrincipalAccount" = local.account_id } }
      }]
    }
  }
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = local.endpoint_policies
  vpc_id              = aws_vpc.this.id
  service_name        = "com.amazonaws.${local.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
  policy              = jsonencode(each.value)
  tags                = { Name = "${var.name}-${each.key}" }
}

resource "aws_cloudwatch_log_group" "flow_logs" {
  name              = "/vpc/${var.name}-flow-logs"
  retention_in_days = var.log_retention_days
  kms_key_id        = aws_kms_key.api.arn
}

resource "aws_iam_role" "flow_logs" {
  name = "${var.name}-flow-logs"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "vpc-flow-logs.amazonaws.com" }
      Action    = "sts:AssumeRole"
      Condition = { StringEquals = { "aws:SourceAccount" = local.account_id } }
    }]
  })
}

resource "aws_iam_role_policy" "flow_logs" {
  name = "flow-logs"
  role = aws_iam_role.flow_logs.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["logs:CreateLogStream", "logs:PutLogEvents", "logs:DescribeLogStreams"]
      Resource = "${aws_cloudwatch_log_group.flow_logs.arn}:*"
    }]
  })
}

resource "aws_flow_log" "this" {
  vpc_id          = aws_vpc.this.id
  traffic_type    = "ALL"
  log_destination = aws_cloudwatch_log_group.flow_logs.arn
  iam_role_arn    = aws_iam_role.flow_logs.arn
}
