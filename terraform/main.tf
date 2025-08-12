
#############################################
# Terraform configuration and provider setup
#############################################

terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = ">= 6.0, < 7.0"
    }
    random = {
      source  = "hashicorp/random"
      version = ">= 3.0, < 4.0"
    }
  }
}

# AWS provider - using Ireland region (eu-west-1)
# You can change this region if needed.
provider "aws" {
  region = "eu-west-1" # change if you like
}

#############################################
# S3 bucket for file storage
#############################################

# Generate a random suffix for bucket name to avoid name collisions
resource "random_id" "bucket_id" {
  byte_length = 4
}

# Create the S3 bucket

resource "aws_s3_bucket" "files" {
  bucket        = "resmed-file-storage-${random_id.bucket_id.hex}"
  force_destroy = true
}

# Block all public access to this S3 bucket

resource "aws_s3_bucket_public_access_block" "files" {
  bucket                  = aws_s3_bucket.files.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

#############################################
# DynamoDB table to store file metadata
#############################################

resource "aws_dynamodb_table" "files" {
  name         = "files-table"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "file_id"

  attribute {
    name = "file_id"
    type = "S"
  }
}

#############################################
# IAM role and permissions for Lambda function
#############################################

# Trust policy: allow Lambda service to assume this role
data "aws_iam_policy_document" "assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

# IAM role for Lambda function
resource "aws_iam_role" "lambda_role" {
  name               = "lambda_s3_dynamo_role"
  assume_role_policy = data.aws_iam_policy_document.assume.json
}

# Attach basic execution role for CloudWatch logging
resource "aws_iam_role_policy_attachment" "lambda_basic" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

# Attach full S3 access (for demo purposes)
resource "aws_iam_role_policy_attachment" "lambda_s3" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonS3FullAccess"
}

# Attach full DynamoDB access (for demo purposes)
resource "aws_iam_role_policy_attachment" "lambda_dynamodb" {
  role       = aws_iam_role.lambda_role.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonDynamoDBFullAccess"
}

#############################################
# Lambda function to handle API requests
#############################################

resource "aws_lambda_function" "api_handler" {
  function_name = "api-handler"
  role          = aws_iam_role.lambda_role.arn
  handler       = "main.lambda_handler"
  runtime       = "python3.12"
  timeout       = 15

 # Path to zipped Lambda code
  filename         = "${path.module}/../lambdas/api_handler/api_handler.zip"
  source_code_hash = filebase64sha256("${path.module}/../lambdas/api_handler/api_handler.zip")

# Environment variables for Lambda
  environment {
    variables = {
      BUCKET_NAME = aws_s3_bucket.files.bucket
      TABLE_NAME  = aws_dynamodb_table.files.name
    }
  }
}

#############################################
# API Gateway HTTP API configuration
#############################################

# Create HTTP API Gateway
resource "aws_apigatewayv2_api" "http" {
  name          = "file-api"
  protocol_type = "HTTP"
}

# Allow API Gateway to invoke Lambda
resource "aws_lambda_permission" "allow_apigw" {
  statement_id  = "AllowAPIGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api_handler.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.http.execution_arn}/*/*"
}

# Connect API Gateway with Lambda (AWS_PROXY integration)
resource "aws_apigatewayv2_integration" "lambda_integration" {
  api_id                 = aws_apigatewayv2_api.http.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api_handler.invoke_arn
  payload_format_version = "2.0"
}

# Routes mapping HTTP methods and paths to the Lambda function
resource "aws_apigatewayv2_route" "get_root" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}


resource "aws_apigatewayv2_route" "get_health" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /health"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "post_upload" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "POST /upload"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "get_files" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /files"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

resource "aws_apigatewayv2_route" "get_file_by_id" {
  api_id    = aws_apigatewayv2_api.http.id
  route_key = "GET /files/{file_id}"
  target    = "integrations/${aws_apigatewayv2_integration.lambda_integration.id}"
}

# Deploy the API with the default stage (auto-deploy enabled)
resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.http.id
  name        = "$default"
  auto_deploy = true
}
