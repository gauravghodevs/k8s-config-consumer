import base64
import hashlib
import json
import boto3
import yaml

s3 = boto3.client("s3")
MAX_BYTES = 1048576


def validate_config(content):
    if not content or len(content) > MAX_BYTES:
        return False, "Invalid size"

    try:
        config = yaml.safe_load(content)
    except yaml.YAMLError:
        return False, "Malformed YAML"

    if not isinstance(config, dict):
        return False, "Configuration must be an object"

    version = config.get("version")
    rules = config.get("rules")

    if not isinstance(version, str) or not version:
        return False, "Missing or invalid version"

    if not isinstance(rules, list) or not rules:
        return False, "Missing or invalid rules"

    for rule in rules:
        if not isinstance(rule, dict):
            return False, "Invalid rule"

        if not isinstance(rule.get("name"), str) or not rule["name"]:
            return False, "Invalid rule name"

        if rule.get("action") not in ("allow", "deny", "rate_limit"):
            return False, "Invalid rule action"

    return True, hashlib.sha256(content).hexdigest()


def response(status, result):
    return {
        "statusCode": status,
        "body": json.dumps(result)
    }


def lambda_handler(event, context):
    try:
        if "detail" in event and "bucket" in event["detail"]:
            bucket = event["detail"]["bucket"]["name"]
            key = event["detail"]["object"]["key"]

            obj = s3.get_object(Bucket=bucket, Key=key)

            if obj["ContentLength"] > MAX_BYTES:
                return response(400, {"valid": False, "reason": "Oversized S3 object"})

            content = obj["Body"].read(MAX_BYTES + 1)

        else:
            body = event.get("body") or ""

            if event.get("isBase64Encoded"):
                content = base64.b64decode(body)
            else:
                content = body.encode("utf-8")

        valid, result = validate_config(content)

        if not valid:
            return response(422, {"valid": False, "reason": result})

        return response(200, {
            "valid": True,
            "sha256": result,
            "bytes": len(content)
        })

    except Exception as exc:
        print(f"Validation error: {exc}")
        return response(500, {"valid": False, "reason": "Internal validation error"})
