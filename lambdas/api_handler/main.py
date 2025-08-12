
#import necessary libraries
import json
import os
import uuid
import logging
from datetime import datetime, timezone
from urllib.parse import unquote
from decimal import Decimal  # DynamoDB returns numbers as Decimal objects

import boto3
# -----------------------
# AWS CLIENT SETUP
# -----------------------

# Logging goes to CloudWatch Logs
logger = logging.getLogger()
logger.setLevel(logging.INFO)

# Create AWS SDK clients for S3 and DynamoDB
s3 = boto3.client("s3")
dynamodb = boto3.resource("dynamodb")

# Load resource names from environment variables set in Lambda configuration
BUCKET_NAME = os.environ["BUCKET_NAME"]
TABLE_NAME = os.environ["TABLE_NAME"]
table = dynamodb.Table(TABLE_NAME)

# Max file size limit (20 MB)
MAX_BYTES = 20 * 1024 * 1024  # 20 MB size cap

# -----------------------
# HELPER FUNCTIONS
# -----------------------

"""
    Helper to return an HTTP-style API Gateway response.
    Defaults to application/json, but can merge custom headers.
"""

def _resp(status: int, body: dict, headers: dict | None = None) -> dict:
    out = {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }
    if headers:
        out["headers"].update(headers)
    return out

"""
    Normalizes the incoming event from API Gateway
    so it works with both v2.0 HTTP APIs and v1.0 REST APIs.
    Returns:
        (HTTP method, path)
    """
def _parse_request(event: dict) -> tuple[str, str]:
    rc = event.get("requestContext") or {}
    http = rc.get("http")
    if isinstance(http, dict) and "method" in http:  # v2
        return http.get("method", ""), event.get("rawPath", "")

    # v1 fallback
    return event.get("httpMethod", ""), event.get("path", "")

"""
    Parses the incoming request body as JSON if present.
    Returns an empty dict if no body or parsing fails.
    """
def _json_body(event: dict) -> dict:
    try:
        body = event.get("body")
        if body is None:
            return {}
        return json.loads(body)
    except Exception:
        return {}


"""
    Recursively convert DynamoDB's Decimal values into int or float
    so the JSON serializer can handle them without errors.
    """
def _convert_decimals(obj):
    if isinstance(obj, list):
        return [_convert_decimals(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _convert_decimals(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        # Convert whole numbers to int, others to float
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


# -----------------------
# MAIN HANDLER
# -----------------------

"""
    Entry point for AWS Lambda.
    Routes the request to the correct handler based on HTTP method & path.
    """
def lambda_handler(event, context):
    logger.info("EVENT: %s", json.dumps(event, default=str))

    method, path = _parse_request(event)

    # Health check
    if method == "GET" and (path == "/" or path == "/health"):
        return _resp(200, {"status": "ok"})

    # Upload a file
    if method == "POST" and path == "/upload":
        return handle_upload(event)

    # List all files
    if method == "GET" and path == "/files":
        return handle_list()

  # Download a file by ID
    if method == "GET" and path.startswith("/files/"):
        file_id = unquote(path.split("/files/", 1)[1])
        return handle_download(file_id)
 # Anything else → 404
    return _resp(404, {"error": "Not Found"})


# -----------------------
# ENDPOINT IMPLEMENTATIONS
# -----------------------

def handle_upload(event):
    """
    Handles POST /upload
    Expected JSON body:
    {
        "file_name": "hello.txt",
        "file_content": "Hello AWS!",      # base64 or plain string
        "content_type": "text/plain"       # optional MIME type
    }
    """
    body = _json_body(event)
    file_name = body.get("file_name")
    file_content = body.get("file_content")
    content_type = body.get("content_type") or "text/plain"

    # Validate inputs
    if not file_name or file_content is None:
        return _resp(400, {"error": "Provide file_name and file_content"})
   # Convert content to bytes and check size
    data = file_content.encode() if isinstance(file_content, str) else file_content
    size_bytes = len(data)
    if size_bytes > MAX_BYTES:
        return _resp(413, {"error": "File too large (>20MB)"})
  # Generate unique file ID and S3 object key
    file_id = str(uuid.uuid4())
    key = f"{file_id}_{file_name}"
   # Upload file to S3
    try:
        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"file-id": file_id, "original-name": file_name},
        )
    except Exception as e:
        logger.exception("S3 put_object failed")
        return _resp(500, {"error": f"S3 upload failed: {str(e)}"})
    # Store metadata in DynamoDB
    try:
        table.put_item(
            Item={
                "file_id": file_id,
                "file_name": file_name,
                "size": size_bytes,  # int going in
                "upload_timestamp": datetime.now(timezone.utc).isoformat(),
                "content_type": content_type,
            }
        )
    except Exception as e:
        logger.exception("DynamoDB put_item failed")
        return _resp(500, {"error": f"DynamoDB write failed: {str(e)}"})

    return _resp(200, {"file_id": file_id, "file_name": file_name})


"""
    Handles GET /files
    Retrieves all file metadata from DynamoDB, sorted by upload time (newest first).
    """
def handle_list():
    try:
        resp = table.scan()
        items = resp.get("Items", [])
        # Convert Decimals to native JSON types
        items = _convert_decimals(items)
        items.sort(key=lambda x: x.get("upload_timestamp", ""), reverse=True)
        return _resp(200, items)
    except Exception as e:
        logger.exception("DynamoDB scan failed")
        return _resp(500, {"error": f"DynamoDB scan failed: {str(e)}"})

"""
    Handles GET /files/{file_id}
    Generates a pre-signed S3 URL for the file so the client can download it directly.
    """
def handle_download(file_id: str):
    # Fetch metadata from DynamoDB
    try:
        res = table.get_item(Key={"file_id": file_id})
        item = res.get("Item")
        if not item:
            return _resp(404, {"error": "File not found"})
        # Convert any Decimals just in case
        item = _convert_decimals(item)
    except Exception as e:
        logger.exception("DynamoDB get_item failed")
        return _resp(500, {"error": f"DynamoDB read failed: {str(e)}"})

    file_name = item["file_name"]
    key = f"{file_id}_{file_name}"
    # Generate pre-signed URL to download from S3
    try:
        url = s3.generate_presigned_url(
            "get_object",
            Params={"Bucket": BUCKET_NAME, "Key": key},
            ExpiresIn=3600, # URL valid for 1 hour
        )
        return _resp(200, {"file_id": file_id, "file_name": file_name, "download_url": url})
    except Exception as e:
        logger.exception("Presign failed")
        return _resp(500, {"error": f"Could not generate download URL: {str(e)}"})


