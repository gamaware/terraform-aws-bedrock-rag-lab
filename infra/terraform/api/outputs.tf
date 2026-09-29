output "api_id" {
  description = "REST API ID."
  value       = aws_api_gateway_rest_api.this.id
}

output "ask_url" {
  description = "POST URL, resolvable only inside the VPC (private DNS on the execute-api endpoint)."
  value       = "https://${aws_api_gateway_rest_api.this.id}.execute-api.${local.region}.amazonaws.com/${aws_api_gateway_stage.v1.stage_name}/ask"
}

output "ask_function_name" {
  description = "Ask function name (the live test invokes it directly with the same event API Gateway sends)."
  value       = aws_lambda_function.ask.function_name
}

output "inference_profile_arn" {
  description = "Application inference profile the function calls; its tags drive cost allocation."
  value       = aws_bedrock_inference_profile.answers.arn
}

output "vpc_id" {
  description = "Private VPC that holds the function and the endpoints."
  value       = aws_vpc.this.id
}
