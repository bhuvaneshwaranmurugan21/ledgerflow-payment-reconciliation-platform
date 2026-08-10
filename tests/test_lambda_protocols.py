from __future__ import annotations

import base64
import io
import json
import os
from typing import Any

os.environ.setdefault("AWS_DEFAULT_REGION", "ap-south-1")
os.environ.setdefault("AWS_ACCESS_KEY_ID", "synthetic-test-key")
os.environ.setdefault("AWS_SECRET_ACCESS_KEY", "synthetic-test-secret")
os.environ.setdefault("AWS_EC2_METADATA_DISABLED", "true")

from lambdas.manifest_loader import handler as manifest_loader  # noqa: E402
from lambdas.schema_identity_gate import handler as identity_gate  # noqa: E402


class ManifestS3:
    def __init__(self, manifest: dict[str, Any], payload: bytes) -> None:
        self.manifest = manifest
        self.payload = payload
        self.copy_request: dict[str, Any] | None = None

    def get_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {"Body": io.BytesIO(json.dumps(self.manifest).encode())}

    def head_object(self, **_kwargs: Any) -> dict[str, Any]:
        return {
            "ContentLength": len(self.payload),
            "ChecksumSHA256": base64.b64encode(bytes.fromhex(self.manifest["sha256"])).decode(),
            "ETag": '"synthetic-etag"',
            "VersionId": "source-version-7",
        }

    def copy_object(self, **kwargs: Any) -> dict[str, Any]:
        self.copy_request = kwargs
        return {
            "CopyObjectResult": {
                "ChecksumSHA256": base64.b64encode(
                    bytes.fromhex(self.manifest["sha256"])
                ).decode()
            }
        }


class ActiveRevisionTable:
    def __init__(self) -> None:
        self.update_request: dict[str, Any] | None = None

    def update_item(self, **kwargs: Any) -> None:
        self.update_request = kwargs


class StepFunctionsRecorder:
    def __init__(self) -> None:
        self.request: dict[str, Any] | None = None

    def start_execution(self, **kwargs: Any) -> dict[str, str]:
        self.request = kwargs
        return {"executionArn": "arn:aws:states:ap-south-1:123:execution:test"}


def test_manifest_processing_is_bound_to_checked_s3_version(monkeypatch: Any) -> None:
    payload = b'{"settlement":"synthetic"}\n'
    digest = __import__("hashlib").sha256(payload).hexdigest()
    manifest = {
        "version": 1,
        "revision": 7,
        "file_name": "daily.jsonl",
        "byte_size": len(payload),
        "record_count": 1,
        "sha256": digest,
        "raw_control_totals_minor": {"INR": 100},
    }
    fake_s3 = ManifestS3(manifest, payload)
    fake_table = ActiveRevisionTable()
    fake_sfn = StepFunctionsRecorder()
    monkeypatch.setattr(manifest_loader, "s3", fake_s3)
    monkeypatch.setattr(manifest_loader, "dynamodb", fake_table)
    monkeypatch.setattr(manifest_loader, "sfn", fake_sfn)
    monkeypatch.setenv("VERIFIED_SETTLEMENT_BUCKET", "verified-input")
    monkeypatch.setenv("SETTLEMENT_PUBLICATION_TABLE", "publication-registry")
    monkeypatch.setenv("SETTLEMENT_STATE_MACHINE_ARN", "arn:aws:states:test")
    monkeypatch.setenv("KMS_KEY_ARN", "arn:aws:kms:test")

    result = manifest_loader.handler(
        {
            "detail": {
                "bucket": {"name": "landing"},
                "object": {
                    "key": "settlements/business_date=2026-08-09/daily.manifest.json"
                },
            }
        },
        None,
    )

    assert result["status"] == "VERIFIED"
    assert fake_s3.copy_request is not None
    assert fake_s3.copy_request["CopySource"]["VersionId"] == "source-version-7"
    assert fake_table.update_request is not None
    assert "revision < :revision" in fake_table.update_request["ConditionExpression"]
    assert fake_sfn.request is not None
    workflow_input = json.loads(fake_sfn.request["input"])
    assert workflow_input["source_version_id"] == "source-version-7"
    assert workflow_input["revision"] == 7


def test_card_security_data_never_reaches_bronze(monkeypatch: Any) -> None:
    raw = {"event_id": "evt-sensitive", "nested": {"CVV": "123"}}
    encoded = base64.b64encode(json.dumps(raw).encode()).decode()
    writes: list[tuple[str, str]] = []
    monkeypatch.setattr(identity_gate, "_registry", lambda: {})
    monkeypatch.setattr(identity_gate, "_token_key", lambda: b"x" * 32)
    monkeypatch.setattr(
        identity_gate,
        "_put_json",
        lambda bucket, key, _value: writes.append((bucket, key)),
    )
    monkeypatch.setenv("BRONZE_BUCKET", "bronze")
    monkeypatch.setenv("QUARANTINE_BUCKET", "quarantine")

    result = identity_gate.handler(
        {"Records": [{"eventID": "record-1", "kinesis": {"data": encoded}}]},
        None,
    )

    assert result == {"batchItemFailures": []}
    assert writes == [("quarantine", "contract/record-1.json")]
