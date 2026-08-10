"""Verify a delivered settlement manifest, then start its owned state machine."""

from __future__ import annotations

import base64
import json
import os
import re
from typing import Any

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")
sfn = boto3.client("stepfunctions")
dynamodb = boto3.client("dynamodb")
BUSINESS_DATE = re.compile(r"(?:^|/)business_date=(\d{4}-\d{2}-\d{2})(?:/|$)")
MAX_SINGLE_COPY_BYTES = 5_000_000_000


def _record(event: dict[str, Any]) -> tuple[str, str]:
    detail = event.get("detail", {})
    bucket = detail.get("bucket", {}).get("name")
    key = detail.get("object", {}).get("key")
    if (
        not isinstance(bucket, str)
        or not isinstance(key, str)
        or not key.endswith(".manifest.json")
    ):
        raise ValueError("event does not identify a settlement manifest")
    return bucket, key


def _register_revision(business_date: str, revision: int, sha256: str, key: str) -> str:
    """Make the newest revision authoritative; equal revisions must be byte-identical."""
    try:
        dynamodb.update_item(
            TableName=os.environ["SETTLEMENT_PUBLICATION_TABLE"],
            Key={"business_date": {"S": business_date}},
            UpdateExpression=(
                "SET revision = :revision, manifest_sha256 = :sha, verified_data_key = :key, "
                "publication_status = :processing"
            ),
            ConditionExpression="attribute_not_exists(revision) OR revision < :revision",
            ExpressionAttributeValues={
                ":revision": {"N": str(revision)},
                ":sha": {"S": sha256},
                ":key": {"S": key},
                ":processing": {"S": "PROCESSING"},
            },
        )
        return "ACTIVE"
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
    existing = dynamodb.get_item(
        TableName=os.environ["SETTLEMENT_PUBLICATION_TABLE"],
        Key={"business_date": {"S": business_date}},
        ConsistentRead=True,
    )["Item"]
    existing_revision = int(existing["revision"]["N"])
    existing_sha = existing["manifest_sha256"]["S"]
    if existing_revision == revision and existing_sha == sha256:
        return "DUPLICATE"
    if existing_revision > revision:
        return "STALE"
    raise ValueError("settlement revision reused with different content")


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    bucket, manifest_key = _record(event)
    data_key = manifest_key.removesuffix(".manifest.json") + ".jsonl"
    manifest_object = s3.get_object(Bucket=bucket, Key=manifest_key)
    manifest = json.loads(manifest_object["Body"].read())
    if not isinstance(manifest, dict):
        raise ValueError("manifest must be a JSON object")
    required = {
        "version",
        "revision",
        "file_name",
        "byte_size",
        "record_count",
        "sha256",
        "raw_control_totals_minor",
    }
    if set(manifest) != required or manifest.get("version") != 1:
        raise ValueError("unsupported settlement manifest contract")
    if (
        not isinstance(manifest.get("record_count"), int)
        or manifest["record_count"] < 1
        or not isinstance(manifest.get("revision"), int)
        or manifest["revision"] < 1
        or not isinstance(manifest.get("byte_size"), int)
        or not 0 < manifest["byte_size"] <= MAX_SINGLE_COPY_BYTES
        or not isinstance(manifest.get("raw_control_totals_minor"), dict)
    ):
        raise ValueError("invalid settlement manifest control values")
    head = s3.head_object(Bucket=bucket, Key=data_key, ChecksumMode="ENABLED")
    source_version_id = head.get("VersionId")
    if not isinstance(source_version_id, str):
        raise ValueError("settlement source must be an S3-versioned object")
    if manifest.get("file_name") != data_key.rsplit("/", 1)[-1]:
        raise ValueError("manifest file name does not match delivered object")
    if manifest.get("byte_size") != head["ContentLength"]:
        raise ValueError("manifest byte size does not match delivered object")
    managed_checksum = head.get("ChecksumSHA256")
    if not isinstance(managed_checksum, str):
        raise ValueError("settlement object must carry an S3 SHA-256 checksum")
    # S3 returns the checksum bytes encoded as base64; convert those bytes to hex.
    checksum_hex = base64.b64decode(managed_checksum).hex()
    if not isinstance(manifest.get("sha256"), str) or manifest["sha256"] != checksum_hex:
        raise ValueError("manifest checksum does not match S3-managed checksum")
    date_match = BUSINESS_DATE.search(data_key)
    if date_match is None:
        raise ValueError("settlement key must contain business_date=YYYY-MM-DD")
    business_date = date_match.group(1)
    verified_data_key = (
        f"settlements/business_date={business_date}/revision={manifest['revision']}/"
        f"sha256={manifest['sha256']}/data.jsonl"
    )
    copy_result = s3.copy_object(
        Bucket=os.environ["VERIFIED_SETTLEMENT_BUCKET"],
        Key=verified_data_key,
        CopySource={"Bucket": bucket, "Key": data_key, "VersionId": source_version_id},
        CopySourceIfMatch=head["ETag"],
        ChecksumAlgorithm="SHA256",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["KMS_KEY_ARN"],
    )
    copied_checksum = copy_result.get("CopyObjectResult", {}).get("ChecksumSHA256")
    copied_checksum_hex = (
        base64.b64decode(copied_checksum).hex() if isinstance(copied_checksum, str) else None
    )
    if copied_checksum_hex != checksum_hex:
        raise ValueError("verified settlement copy checksum mismatch")
    registration = _register_revision(
        business_date,
        manifest["revision"],
        manifest["sha256"],
        verified_data_key,
    )
    if registration == "STALE":
        return {"status": "STALE_MANIFEST", "revision": manifest["revision"]}
    execution_name = (
        f"{business_date}-r{manifest['revision']}-{manifest['sha256'][:16]}"
    )
    try:
        execution = sfn.start_execution(
            stateMachineArn=os.environ["SETTLEMENT_STATE_MACHINE_ARN"],
            name=execution_name,
            input=json.dumps(
                {
                    "manifest_bucket": bucket,
                    "manifest_key": manifest_key,
                    "verified_bucket": os.environ["VERIFIED_SETTLEMENT_BUCKET"],
                    "verified_data_key": verified_data_key,
                    "source_version_id": source_version_id,
                    "sha256": manifest["sha256"],
                    "revision": manifest["revision"],
                    "record_count": manifest["record_count"],
                    "business_date": business_date,
                }
            ),
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") == "ExecutionAlreadyExists":
            return {"status": "DUPLICATE_MANIFEST", "execution_name": execution_name}
        raise
    return {
        "status": "VERIFIED" if registration == "ACTIVE" else "RECOVERED_DUPLICATE",
        "execution_arn": execution["executionArn"],
    }
