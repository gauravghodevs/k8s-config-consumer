import hashlib

from controller.s3_store import S3ConfigStore


class FakeS3Client:
    def __init__(self):
        self.put_calls = []
        self.get_calls = []

    def put_object(self, **kwargs):
        self.put_calls.append(kwargs)

        return {
            "VersionId": "version-123",
            "ETag": '"etag-123"',
        }

    def get_object(self, **kwargs):
        self.get_calls.append(kwargs)

        if kwargs["Key"].endswith("rules.yaml.sig"):
            content = b"BASE64-SIGNATURE"
        else:
            content = b"version: 1.4\n"

        return {
            "Body": FakeBody(content),
            "VersionId": "version-123",
            "ETag": '"etag-123"',
        }


class FakeBody:
    def __init__(self, content):
        self.content = content

    def read(self):
        return self.content


def build_store(monkeypatch):
    monkeypatch.setenv(
        "S3_BUCKET",
        "test-bucket",
    )

    store = S3ConfigStore.__new__(
        S3ConfigStore
    )

    store.bucket = "test-bucket"
    store.prefix = "blast-radius-guard/configs"
    store.region = "ap-south-1"
    store.client = FakeS3Client()

    return store


def test_upload_config(monkeypatch):
    store = build_store(monkeypatch)

    content = "version: 1.4\n"

    result = store.upload_config(
        "1.4",
        content,
    )

    expected_sha256 = hashlib.sha256(
        content.encode("utf-8")
    ).hexdigest()

    assert result["key"] == (
        "blast-radius-guard/configs/"
        "version-1.4/rules.yaml"
    )

    assert result["version_id"] == "version-123"
    assert result["etag"] == "etag-123"
    assert result["sha256"] == expected_sha256

    call = store.client.put_calls[0]

    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == result["key"]
    assert call["Body"] == content.encode("utf-8")
    assert call["Metadata"]["config-version"] == "1.4"
    assert call["Metadata"]["sha256"] == expected_sha256


def test_upload_signature(monkeypatch):
    store = build_store(monkeypatch)

    signature = "BASE64-SIGNATURE"

    result = store.upload_signature(
        "1.4",
        signature,
    )

    assert result["key"] == (
        "blast-radius-guard/configs/"
        "version-1.4/rules.yaml.sig"
    )

    assert result["version_id"] == "version-123"
    assert result["etag"] == "etag-123"

    call = store.client.put_calls[0]

    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == result["key"]
    assert call["Body"] == signature.encode("utf-8")
    assert call["ContentType"] == "text/plain"
    assert call["Metadata"]["config-version"] == "1.4"


def test_download_config_with_version_id(monkeypatch):
    store = build_store(monkeypatch)

    result = store.download_config(
        "1.4",
        version_id="version-123",
    )

    expected_content = b"version: 1.4\n"

    expected_sha256 = hashlib.sha256(
        expected_content
    ).hexdigest()

    assert result["content"] == (
        "version: 1.4\n"
    )

    assert result["version_id"] == "version-123"
    assert result["etag"] == "etag-123"
    assert result["sha256"] == expected_sha256

    call = store.client.get_calls[0]

    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == (
        "blast-radius-guard/configs/"
        "version-1.4/rules.yaml"
    )
    assert call["VersionId"] == "version-123"

def test_download_signature_with_version_id(monkeypatch):
    store = build_store(monkeypatch)

    result = store.download_signature(
        "1.4",
        version_id="version-123",
    )

    assert result["signature"] == "BASE64-SIGNATURE"
    assert result["version_id"] == "version-123"
    assert result["etag"] == "etag-123"

    call = store.client.get_calls[0]

    assert call["Bucket"] == "test-bucket"
    assert call["Key"] == (
        "blast-radius-guard/configs/"
        "version-1.4/rules.yaml.sig"
    )
    assert call["VersionId"] == "version-123"

