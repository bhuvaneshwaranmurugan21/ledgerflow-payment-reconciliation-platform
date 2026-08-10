"""Source registry, schema gate, stable identity and privacy boundary."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
EVENT_TYPES = ("authorization", "capture", "refund", "chargeback")
CURRENCIES = ("INR", "USD", "EUR", "GBP")
PROHIBITED_FIELDS = frozenset(
    {
        "card_number",
        "cardnumber",
        "pan",
        "cvv",
        "cvc",
        "security_code",
        "track_data",
        "pin",
        "full_card_number",
    }
)
IDENTIFIER = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "event_id",
        "transaction_id",
        "transaction_version",
        "source_id",
        "processor_id",
        "merchant_id",
        "event_type",
        "amount_minor",
        "currency",
        "event_time",
        "received_at",
    }
)
ALLOWED_FIELDS = REQUIRED_FIELDS | {"customer_email"}
IDENTITY_FIELDS = (
    "schema_version",
    "event_id",
    "transaction_id",
    "transaction_version",
    "source_id",
    "processor_id",
    "merchant_id",
    "event_type",
    "amount_minor",
    "currency",
    "event_time",
    "customer_email",
)


class ContractError(ValueError):
    """Raised when a source or event violates the ingestion contract."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Source:
    source_id: str
    family: str
    mode: str
    contract: str
    owner: str
    freshness_minutes: int


@dataclass(frozen=True)
class PaymentEvent:
    schema_version: str
    event_id: str
    transaction_id: str
    transaction_version: int
    source_id: str
    processor_id: str
    merchant_id: str
    event_type: str
    amount_minor: int
    currency: str
    event_time: str
    received_at: str
    customer_token: str | None

    def safe_dict(self) -> dict[str, str | int | None]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "transaction_id": self.transaction_id,
            "transaction_version": self.transaction_version,
            "source_id": self.source_id,
            "processor_id": self.processor_id,
            "merchant_id": self.merchant_id,
            "event_type": self.event_type,
            "amount_minor": self.amount_minor,
            "currency": self.currency,
            "event_time": self.event_time,
            "received_at": self.received_at,
            "customer_token": self.customer_token,
        }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def load_source_registry(path: str | Path) -> dict[str, Source]:
    raw = read_json(path)
    registry: dict[str, Source] = {}
    modes = {"stream", "cdc", "manifest_file"}
    for family in raw.get("families", []):
        required = {"family", "instances", "mode", "contract", "owner", "freshness_minutes"}
        missing = required - family.keys()
        if missing:
            raise ContractError("source_family_missing:" + ",".join(sorted(missing)))
        if family["mode"] not in modes:
            raise ContractError(f"unsupported_source_mode:{family['mode']}")
        if family["contract"] not in {"payment_event", "settlement_evidence"}:
            raise ContractError(f"unsupported_source_contract:{family['contract']}")
        if not isinstance(family["instances"], int) or family["instances"] < 1:
            raise ContractError("invalid_source_instances")
        if not isinstance(family["freshness_minutes"], int) or family["freshness_minutes"] < 1:
            raise ContractError("invalid_freshness_minutes")
        for number in range(1, family["instances"] + 1):
            source_id = f"{family['family']}-{number:02d}"
            if source_id in registry:
                raise ContractError(f"duplicate_source:{source_id}")
            registry[source_id] = Source(
                source_id=source_id,
                family=str(family["family"]),
                mode=str(family["mode"]),
                contract=str(family["contract"]),
                owner=str(family["owner"]),
                freshness_minutes=int(family["freshness_minutes"]),
            )
    if not registry:
        raise ContractError("empty_source_registry")
    return registry


def _parse_utc_timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ContractError(f"invalid_{field}")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ContractError(f"invalid_{field}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ContractError(f"timezone_required:{field}")
    return parsed.isoformat()


def _validate_identifier(value: Any, field: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ContractError(f"invalid_{field}")
    return value


def tokenize_customer(value: str | None, key: bytes) -> str | None:
    if value is None:
        return None
    if len(key) < 32:
        raise ContractError("token_key_too_short")
    normalized = value.strip().lower().encode("utf-8")
    return hmac.new(key, normalized, hashlib.sha256).hexdigest()


def identity_fingerprint(raw: dict[str, Any]) -> str:
    identity = {field: raw.get(field) for field in IDENTITY_FIELDS if field in raw}
    email = identity.get("customer_email")
    if isinstance(email, str):
        identity["customer_email"] = email.strip().lower()
    return sha256_text(canonical_json(identity))


def redact_payload(raw: dict[str, Any]) -> dict[str, Any]:
    sensitive = PROHIBITED_FIELDS | {"customer_email"}

    def redact(value: Any) -> Any:
        if isinstance(value, dict):
            return {
                key: "<redacted>" if key.casefold() in sensitive else redact(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [redact(item) for item in value]
        return value

    return dict(redact(raw))


def reject_prohibited_fields(raw: dict[str, Any]) -> None:
    """Reject card-security fields at any depth before durable raw persistence."""
    found: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                normalized = key.casefold()
                if normalized in PROHIBITED_FIELDS:
                    found.add(normalized)
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(raw)
    if found:
        raise ContractError("prohibited_fields:" + ",".join(sorted(found)))


def extract_business_payload(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize an approved DMS outbox envelope or return a direct event."""
    metadata = raw.get("metadata")
    data = raw.get("data")
    if metadata is None and data is None:
        return raw
    if not isinstance(metadata, dict) or not isinstance(data, dict):
        raise ContractError("invalid_cdc_envelope")
    if metadata.get("table-name") != "payment_outbox":
        raise ContractError("unsupported_cdc_table")
    if metadata.get("operation") not in {"insert", "load"}:
        raise ContractError("non_insert_outbox_mutation")
    return data


def validate_event(
    raw: dict[str, Any], registry: dict[str, Source], token_key: bytes
) -> PaymentEvent:
    reject_prohibited_fields(raw)
    missing = sorted(REQUIRED_FIELDS - raw.keys())
    if missing:
        raise ContractError("missing_fields:" + ",".join(missing))
    unexpected = sorted(raw.keys() - ALLOWED_FIELDS)
    if unexpected:
        raise ContractError("unexpected_fields:" + ",".join(unexpected))
    if raw["schema_version"] != SCHEMA_VERSION:
        raise ContractError("unsupported_schema_version")
    event_id = _validate_identifier(raw["event_id"], "event_id")
    transaction_id = _validate_identifier(raw["transaction_id"], "transaction_id")
    source_id = _validate_identifier(raw["source_id"], "source_id")
    processor_id = _validate_identifier(raw["processor_id"], "processor_id")
    merchant_id = _validate_identifier(raw["merchant_id"], "merchant_id")
    if source_id not in registry:
        raise ContractError("unknown_source")
    if registry[source_id].contract != "payment_event":
        raise ContractError("source_contract_mismatch")
    transaction_version = raw["transaction_version"]
    if isinstance(transaction_version, bool) or not isinstance(transaction_version, int):
        raise ContractError("invalid_transaction_version")
    if transaction_version < 1:
        raise ContractError("invalid_transaction_version")
    event_type = raw["event_type"]
    if event_type not in EVENT_TYPES:
        raise ContractError("unsupported_event_type")
    amount_minor = raw["amount_minor"]
    if isinstance(amount_minor, bool) or not isinstance(amount_minor, int) or amount_minor <= 0:
        raise ContractError("invalid_amount_minor")
    currency = raw["currency"]
    if currency not in CURRENCIES:
        raise ContractError("unsupported_currency")
    event_time = _parse_utc_timestamp(raw["event_time"], "event_time")
    received_at = _parse_utc_timestamp(raw["received_at"], "received_at")
    email = raw.get("customer_email")
    if email is not None and (not isinstance(email, str) or "@" not in email):
        raise ContractError("invalid_customer_email")
    return PaymentEvent(
        schema_version=SCHEMA_VERSION,
        event_id=event_id,
        transaction_id=transaction_id,
        transaction_version=transaction_version,
        source_id=source_id,
        processor_id=processor_id,
        merchant_id=merchant_id,
        event_type=event_type,
        amount_minor=amount_minor,
        currency=currency,
        event_time=event_time,
        received_at=received_at,
        customer_token=tokenize_customer(email, token_key),
    )
