"""Persist raw Kinesis evidence and classify payment identity without logging PII."""

from __future__ import annotations

import base64
import json
import os
from datetime import UTC, datetime
from typing import Any

import boto3
from botocore.exceptions import ClientError

from ledgerflow.contracts import (
    ContractError,
    PaymentEvent,
    canonical_json,
    extract_business_payload,
    identity_fingerprint,
    load_source_registry,
    redact_payload,
    reject_prohibited_fields,
    validate_event,
)

s3 = boto3.client("s3")
dynamodb = boto3.client("dynamodb")
secrets = boto3.client("secretsmanager")


def _token_key() -> bytes:
    response = secrets.get_secret_value(SecretId=os.environ["TOKEN_SECRET_ARN"])
    value = response.get("SecretString")
    if not isinstance(value, str):
        raise RuntimeError("token secret must be a string")
    return value.encode("utf-8")


def _registry() -> dict[str, Any]:
    path = os.environ.get("SOURCE_REGISTRY_PATH", "/var/task/config/sources.json")
    return load_source_registry(path)


def _put_json(bucket: str, key: str, value: dict[str, Any]) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=(canonical_json(value) + "\n").encode("utf-8"),
        ContentType="application/json",
        ServerSideEncryption="aws:kms",
        SSEKMSKeyId=os.environ["KMS_KEY_ARN"],
        ChecksumAlgorithm="SHA256",
    )


def _publish_accepted(payment: PaymentEvent, fingerprint: str, arrival: datetime) -> None:
    accepted_key = f"accepted/event_date={payment.event_time[:10]}/{payment.event_id}.json"
    try:
        dynamodb.put_item(
            TableName=os.environ["IDENTITY_TABLE"],
            Item={
                "event_id": {"S": payment.event_id},
                "identity_sha256": {"S": fingerprint},
                "first_seen_at": {"S": arrival.isoformat()},
                "publication_status": {"S": "PENDING"},
                "accepted_key": {"S": accepted_key},
            },
            ConditionExpression="attribute_not_exists(event_id)",
        )
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
            raise
        existing = dynamodb.get_item(
            TableName=os.environ["IDENTITY_TABLE"],
            Key={"event_id": {"S": payment.event_id}},
            ConsistentRead=True,
        )["Item"]
        if existing["identity_sha256"]["S"] != fingerprint:
            _put_json(
                os.environ["QUARANTINE_BUCKET"],
                f"identity-conflict/{payment.event_id}.json",
                {
                    "reason": "identity_payload_conflict",
                    "event": payment.safe_dict(),
                },
            )
            return
        if existing.get("publication_status", {}).get("S") == "PUBLISHED":
            return
    _put_json(os.environ["ACCEPTED_BUCKET"], accepted_key, payment.safe_dict())
    dynamodb.update_item(
        TableName=os.environ["IDENTITY_TABLE"],
        Key={"event_id": {"S": payment.event_id}},
        UpdateExpression="SET publication_status = :published",
        ConditionExpression="identity_sha256 = :fingerprint",
        ExpressionAttributeValues={
            ":published": {"S": "PUBLISHED"},
            ":fingerprint": {"S": fingerprint},
        },
    )


def handler(event: dict[str, Any], _context: Any) -> dict[str, Any]:
    registry = _registry()
    token_key = _token_key()
    failures: list[dict[str, str]] = []
    for record in event.get("Records", []):
        record_id = record.get("eventID", "unknown")
        raw: dict[str, Any] = {}
        try:
            decoded = json.loads(base64.b64decode(record["kinesis"]["data"]))
            if not isinstance(decoded, dict):
                raise ContractError("non_object_event")
            raw = decoded
            arrival = datetime.now(UTC)
            business_payload = extract_business_payload(raw)
            reject_prohibited_fields(business_payload)
            raw_key = f"arrivals/date={arrival.date()}/{record_id}.json"
            _put_json(os.environ["BRONZE_BUCKET"], raw_key, raw)
            payment = validate_event(business_payload, registry, token_key)
            fingerprint = identity_fingerprint(business_payload)
            _publish_accepted(payment, fingerprint, arrival)
        except ContractError as error:
            _put_json(
                os.environ["QUARANTINE_BUCKET"],
                f"contract/{record_id}.json",
                {"reason": error.reason, "event": redact_payload(raw)},
            )
        except Exception:
            failures.append({"itemIdentifier": str(record_id)})
    return {"batchItemFailures": failures}
