from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ledgerflow.contracts import Source, identity_fingerprint, sha256_text
from ledgerflow.ledger import PostingRules
from ledgerflow.store import LedgerStore
from tests.conftest import TOKEN_KEY


def events(source_id: str) -> list[dict[str, object]]:
    base = datetime(2026, 1, 1, tzinfo=UTC)

    def row(version: int, event_type: str, amount: int) -> dict[str, object]:
        occurred = base + timedelta(minutes=version)
        return {
            "schema_version": "1.0",
            "event_id": f"txn-1:v{version}",
            "transaction_id": "txn-1",
            "transaction_version": version,
            "source_id": source_id,
            "processor_id": "processor-01",
            "merchant_id": "merchant-001",
            "event_type": event_type,
            "amount_minor": amount,
            "currency": "INR",
            "event_time": occurred.isoformat(),
            "received_at": (occurred + timedelta(minutes=5 - version)).isoformat(),
            "customer_email": "buyer@example.test",
        }

    return [row(3, "refund", 2_500), row(1, "authorization", 10_000), row(2, "capture", 10_000)]


def test_out_of_order_events_reconstruct_then_replay_without_second_effect(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    raw = events(source_id)
    store = LedgerStore(tmp_path / "ledger.sqlite")
    first = store.process(
        run_id="first",
        input_sha256=sha256_text("first"),
        raw_events=raw,
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    replay = store.process(
        run_id="replay",
        input_sha256=sha256_text("first"),
        raw_events=list(reversed(raw)),
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    assert first["business_exception"] == 0
    assert first["raw_records"] == len(raw)
    assert first["raw_reconciled"] is True
    assert first["ledger_entry"] == 4
    assert first["posted_event"] == 2
    assert first["ledger_balanced"] is True
    assert replay["ledger_entry"] == first["ledger_entry"]
    assert replay["payment_state_sha256"] == first["payment_state_sha256"]
    assert replay["duplicates"] == len(raw)


def test_same_event_id_with_changed_money_is_quarantined(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    original = events(source_id)[:2]
    store = LedgerStore(tmp_path / "ledger.sqlite")
    store.process(
        run_id="first",
        input_sha256=sha256_text("first"),
        raw_events=original,
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    conflict = dict(original[0])
    conflict["amount_minor"] = int(conflict["amount_minor"]) + 1
    assert identity_fingerprint(conflict) != identity_fingerprint(original[0])
    result = store.process(
        run_id="conflict",
        input_sha256=sha256_text("conflict"),
        raw_events=[conflict],
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    assert result["outcomes"]["QUARANTINED:identity_payload_conflict"] == 1


def test_crash_before_commit_leaves_no_partial_financial_effect(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    store = LedgerStore(tmp_path / "ledger.sqlite")
    with pytest.raises(RuntimeError, match="injected_failure"):
        store.process(
            run_id="crash",
            input_sha256=sha256_text("crash"),
            raw_events=events(source_id),
            registry=registry,
            token_key=TOKEN_KEY,
            posting_rules=posting_rules,
            failpoint="before_commit",
        )
    assert store.table_count("accepted_event") == 0
    assert store.table_count("ledger_entry") == 0


def test_settlement_difference_blocks_gate(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    store = LedgerStore(tmp_path / "ledger.sqlite")
    store.process(
        run_id="first",
        input_sha256=sha256_text("first"),
        raw_events=events(source_id),
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    expected = store.expected_settlement()
    assert store.reconcile_settlement(expected)["settlement_reconciled"] is True
    expected[0]["amount_minor"] -= 7
    mismatch = store.reconcile_settlement(expected)
    assert mismatch["settlement_reconciled"] is False
    assert mismatch["settlement_absolute_delta_minor"] == 7


def test_business_violation_blocks_entire_transaction(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    raw = events(source_id)[:2]
    raw[0] = {**raw[0], "event_type": "capture", "amount_minor": 15_000}
    raw[1] = {**raw[1], "event_type": "authorization", "amount_minor": 10_000}
    store = LedgerStore(tmp_path / "transaction-gate.sqlite")
    result = store.process(
        run_id="invalid-transaction",
        input_sha256=sha256_text("invalid-transaction"),
        raw_events=raw,
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    assert result["business_exception"] == 2
    assert result["payment_state"] == 0
    assert result["posted_event"] == 0
    assert result["ledger_entry"] == 0


def test_missing_transaction_version_blocks_entire_transaction(
    tmp_path: Path, registry: dict[str, Source], posting_rules: PostingRules
) -> None:
    source_id = next(source.source_id for source in registry.values() if source.mode == "stream")
    raw = [row for row in events(source_id) if row["transaction_version"] != 2]
    store = LedgerStore(tmp_path / "version-gap.sqlite")
    result = store.process(
        run_id="version-gap",
        input_sha256=sha256_text("version-gap"),
        raw_events=raw,
        registry=registry,
        token_key=TOKEN_KEY,
        posting_rules=posting_rules,
    )
    assert result["business_exception"] == 2
    assert result["payment_state"] == 0
    assert result["ledger_entry"] == 0


def test_table_count_rejects_non_allowlisted_sql_identifier(tmp_path: Path) -> None:
    store = LedgerStore(tmp_path / "identifier-gate.sqlite")
    with pytest.raises(ValueError, match="unsupported table"):
        store.table_count("accepted_event; DROP TABLE ledger_entry")
