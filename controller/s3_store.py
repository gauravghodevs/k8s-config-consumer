import hashlib
import os

import boto3


class S3ConfigStore:
    """
    Versioned configuration storage in Amazon S3.

    Required environment variables:
      S3_BUCKET

    Optional:
      S3_PREFIX=blast-radius-guard/configs
      AWS_REGION=ap-south-1
    """

    def __init__(self):
        self.bucket = os.getenv("S3_BUCKET")

        self.prefix = os.getenv(
            "S3_PREFIX",
            "blast-radius-guard/configs"
        ).strip("/")

        self.region = os.getenv(
            "AWS_REGION",
            "ap-south-1"
        )

        if not self.bucket:
            raise RuntimeError(
                "S3_BUCKET environment variable is required"
            )

        self.client = boto3.client(
            "s3",
            region_name=self.region
        )

    def key_for_version(self, version):
        return (
            f"{self.prefix}/"
            f"version-{version}/"
            f"rules.yaml"
        )

    def upload_config(self, version, content):
        key = self.key_for_version(version)

        body = content.encode("utf-8")

        sha256 = hashlib.sha256(body).hexdigest()

        response = self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/x-yaml",
            Metadata={
                "config-version": str(version),
                "sha256": sha256
            }
        )

        return {
            "bucket": self.bucket,
            "key": key,
            "version_id": response.get("VersionId"),
            "etag": response.get("ETag", "").strip('"'),
            "sha256": sha256
        }

    def download_config(self, version, version_id=None):
        key = self.key_for_version(version)

        request = {
            "Bucket": self.bucket,
            "Key": key
        }

        if version_id:
            request["VersionId"] = version_id

        response = self.client.get_object(**request)

        content = response["Body"].read().decode("utf-8")

        return {
            "content": content,
            "version_id": response.get("VersionId"),
            "etag": response.get("ETag", "").strip('"'),
            "sha256": hashlib.sha256(
                content.encode("utf-8")
            ).hexdigest()
        }

    def config_exists(self, version, version_id=None):
        key = self.key_for_version(version)

        request = {
            "Bucket": self.bucket,
            "Key": key
        }

        if version_id:
            request["VersionId"] = version_id

        try:
            self.client.head_object(**request)
            return True
        except self.client.exceptions.ClientError as error:
            if error.response.get("Error", {}).get("Code") in (
                "404",
                "NoSuchKey"
            ):
                return False
            raise
