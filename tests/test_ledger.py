from __future__ import annotations

from datetime import UTC, datetime

import pytest

from ledgerflow.contracts import PaymentEvent
from ledgerflow.ledger import (
    PostingLine,
    PostingRuleError,
    PostingRules,
    assert_balanced,
    build_postings,
)


def payment_event(event_type: str, amount: int = 10_000) -> PaymentEvent:
    now = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    return PaymentEvent(
        schema_version="1.0",
        event_id=f"event:{event_type}",
        transaction_id="txn:1",
        transaction_version=1,
        source_id="checkout-01",
        processor_id="processor-01",
        merchant_id="merchant-001",
        event_type=event_type,
        amount_minor=amount,
        currency="INR",
        event_time=now,
        received_at=now,
        customer_token=None,
    )


def test_every_configured_money_rule_balances(posting_rules: PostingRules) -> None:
    for event_type in ("capture", "refund", "chargeback"):
        lines = build_postings(payment_event(event_type), posting_rules)
        assert len(lines) == 2
        assert sum(line.signed_minor for line in lines) == 0


def test_authorization_has_no_financial_posting(posting_rules: PostingRules) -> None:
    assert build_postings(payment_event("authorization"), posting_rules) == ()


def test_unbalanced_fixture_is_rejected() -> None:
    line = PostingLine(
        entry_id="bad:1",
        event_id="bad",
        transaction_id="txn",
        processor_id="processor",
        merchant_id="merchant",
        currency="INR",
        account="processor_receivable",
        signed_minor=100,
        posting_rule_version=1,
    )
    with pytest.raises(PostingRuleError, match="unbalanced posting group"):
        assert_balanced((line,))
