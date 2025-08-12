# Output the API Gateway endpoint URL
# This will display the public URL of the deployed API after `terraform apply`

output "api_url" {
  value = aws_apigatewayv2_api.http.api_endpoint
}
