#AWS-Lambda-File-Sharing-API-with-Terraform

Steps to Run, Deploy, and Test the AWS File API
1. Prerequisites
AWS account with programmatic access (Access Key & Secret Key).

AWS CLI installed and configured:

bash comment:
aws configure
Python 3.9+ installed.
Terraform installed.

2. Package the Lambda Code

a.Navigate to the Lambda function folder: 
cd lambdas/api_handler

b.Install dependencies into the current directory:
pip install -r requirements.txt -t .

c.Zip the Lambda package:
zip -rq api_handler.zip .

3. Deploy Infrastructure with Terraform

a.Navigate to the Terraform directory:
cd terraform

b.Initialize Terraform:
terraform init -upgrade

c.Apply the configuration:
terraform apply -auto-approve

d.After apply completes, note the output api_url — this is your API Gateway endpoint.


4. Test the API
API="https://quzmpugml4.execute-api.eu-west-1.amazonaws.com" (USE THE PROPER URL)

a.Health Check

curl -s "$API/health"

b.Upload a File (JSON format)
curl -s -X POST "$API/upload" \
  -H "Content-Type: application/json" \
  -d '{
    "file_name": "hello.txt",
    "file_content": "Hello AWS!",
    "content_type": "text/plain"
  }'


c.List All Files
curl -s "$API/files" | jq .

d.Get Download URL for a File
FILE_ID="be2220e0-0c6f-4c32-89c5-e2eb6ed4d43a"
curl -s "$API/files/$FILE_ID" | jq .



e.Test Non-ASCII Filename
curl -s -X POST "$API/upload" \
  -H "Content-Type: application/json" \
  -d '{"file_name":"résumé.txt","file_content":"This is a résumé file.","content_type":"text/plain"}'

5.Test File Size Limit (20MB max)
a.Exactly 20MB
dd if=/dev/zero of=test_20mb.bin bs=1M count=20

# 21MB (should fail)
dd if=/dev/zero of=test_21mb.bin bs=1M count=21

b.Upload 20MB file (should succeed)
base64 test_20mb.bin | \
curl -s -X POST "$API/upload" \
  -H "Content-Type: application/json" \
  -d "{\"file_name\":\"test_20mb.bin\",\"file_content\":\"$(base64 test_20mb.bin)\",\"content_type\":\"application/octet-stream\"}"

c.Upload 21MB file (should fail with 413 or error message):
base64 test_21mb.bin | \
curl -s -X POST "<API_URL>/upload" \
  -H "Content-Type: application/json" \
  -d "{\"file_name\":\"test_21mb.bin\",\"file_content\":\"$(base64 test_21mb.bin)\",\"content_type\":\"application/octet-stream\"}"



6. Verify in AWS Console
Lambda: Function api-handler (your code).
API Gateway: HTTP API file-api.
S3: Bucket containing uploaded files.
DynamoDB: Table files-table storing metadata.


7. Remove Resources

When done testing, destroy resources to avoid AWS costs:

cd terraform
terraform destroy -auto-approve


