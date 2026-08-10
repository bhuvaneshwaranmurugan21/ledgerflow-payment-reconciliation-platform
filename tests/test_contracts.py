from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ledgerflow.contracts import (
    ContractError,
    Source,
    extract_business_payload,
    identity_fingerprint,
    redact_payload,
    tokenize_customer,
    validate_event,
)
from tests.conftest import TOKEN_KEY


def valid_event(source_id: str) -> dict[str, object]:
    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    return {
        "schema_version": "1.0",
        "event_id": "evt-1",
        "transaction_id": "txn-1",
        "transaction_version": 1,
        "source_id": source_id,
        "processor_id": "processor-01",
        "merchant_id": "merchant-001",
        "event_type": "authorization",
        "amount_minor": 10_000,
        "currency": "INR",
        "event_time": now,
        "received_at": now,
        "customer_email": "Buyer@Example.Test",
    }


def test_registry_expands_to_twenty_unique_sources(registry: dict[str, Source]) -> None:
    assert len(registry) == 20
    assert len(set(registry)) == 20
    assert {source.mode for source in registry.values()} == {"stream", "cdc", "manifest_file"}
    assert sum(source.contract == "payment_event" for source in registry.values()) == 17
    assert sum(source.contract == "settlement_evidence" for source in registry.values()) == 3


def test_settlement_source_cannot_enter_payment_event_contract(
    registry: dict[str, Source],
) -> None:
    settlement_source = next(
        source for source in registry.values() if source.contract == "settlement_evidence"
    )
    raw = valid_event(settlement_source.source_id)
    with pytest.raises(ContractError, match="source_contract_mismatch"):
        validate_event(raw, registry, TOKEN_KEY)


def test_hmac_token_is_deterministic_normalized_and_keyed() -> None:
    first = tokenize_customer(" Buyer@Example.Test ", TOKEN_KEY)
    second = tokenize_customer("buyer@example.test", TOKEN_KEY)
    other_key = tokenize_customer(
        "buyer@example.test", b"another-synthetic-key-that-is-long-enough"
    )
    assert first == second
    assert first != other_key
    assert first is not None and len(first) == 64


def test_schema_gate_rejects_prohibited_card_fields(registry: dict[str, Source]) -> None:
    raw = valid_event(next(iter(registry)))
    raw["card_number"] = "4111111111111111"
    with pytest.raises(ContractError, match="prohibited_fields:card_number"):
        validate_event(raw, registry, TOKEN_KEY)


def test_schema_gate_rejects_unknown_fields(registry: dict[str, Source]) -> None:
    raw = valid_event(next(iter(registry)))
    raw["surprise"] = "schema drift"
    with pytest.raises(ContractError, match="unexpected_fields:surprise"):
        validate_event(raw, registry, TOKEN_KEY)


def test_identity_ignores_delivery_time_but_detects_money_change(
    registry: dict[str, Source],
) -> None:
    raw = valid_event(next(iter(registry)))
    delayed = dict(raw)
    delayed["received_at"] = datetime(2026, 1, 2, tzinfo=UTC).isoformat()
    changed = dict(raw)
    changed["amount_minor"] = 10_001
    assert identity_fingerprint(raw) == identity_fingerprint(delayed)
    assert identity_fingerprint(raw) != identity_fingerprint(changed)


def test_event_validation_never_uses_floating_point_money(registry: dict[str, Source]) -> None:
    raw = valid_event(next(iter(registry)))
    raw["amount_minor"] = 100.25
    with pytest.raises(ContractError, match="invalid_amount_minor"):
        validate_event(raw, registry, TOKEN_KEY)


def test_dms_outbox_envelope_is_normalized_and_mutations_are_rejected(
    registry: dict[str, Source],
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "cdc")
    payment = valid_event(source_id)
    envelope = {
        "data": payment,
        "metadata": {"table-name": "payment_outbox", "operation": "insert"},
    }
    assert extract_business_payload(envelope) == payment
    envelope["metadata"]["operation"] = "update"
    with pytest.raises(ContractError, match="non_insert_outbox_mutation"):
        extract_business_payload(envelope)


def test_nested_quarantine_payload_is_recursively_redacted() -> None:
    raw = {
        "data": {
            "customer_email": "buyer@example.test",
            "nested": [{"card_number": "4111111111111111"}],
        }
    }
    redacted = redact_payload(raw)
    assert redacted["data"]["customer_email"] == "<redacted>"
    assert redacted["data"]["nested"][0]["card_number"] == "<redacted>"


def test_nested_mixed_case_card_security_field_is_rejected(
    registry: dict[str, Source],
) -> None:
    raw = valid_event(next(iter(registry)))
    raw["metadata"] = {"payment": {"CVV": "123"}}
    with pytest.raises(ContractError, match="prohibited_fields:cvv"):
        validate_event(raw, registry, TOKEN_KEY)
