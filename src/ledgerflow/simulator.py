"""Deterministic synthetic payment lifecycle and controlled failure fixtures."""

from __future__ import annotations

import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ledgerflow.contracts import CURRENCIES, Source


def _event(
    *,
    transaction_number: int,
    version: int,
    event_type: str,
    amount_minor: int,
    source: Source,
    base_time: datetime,
) -> dict[str, Any]:
    transaction_id = f"txn-{transaction_number:010d}"
    processor_id = f"processor-{transaction_number % 3 + 1:02d}"
    event_time = base_time + timedelta(minutes=version)
    received_at = event_time + timedelta(seconds=(transaction_number * 17 + version * 11) % 240)
    return {
        "schema_version": "1.0",
        "event_id": f"{transaction_id}:v{version}",
        "transaction_id": transaction_id,
        "transaction_version": version,
        "source_id": source.source_id,
        "processor_id": processor_id,
        "merchant_id": f"merchant-{transaction_number % 250:03d}",
        "event_type": event_type,
        "amount_minor": amount_minor,
        "currency": CURRENCIES[transaction_number % len(CURRENCIES)],
        "event_time": event_time.isoformat(),
        "received_at": received_at.isoformat(),
        "customer_email": f"customer{transaction_number % 10000}@example.test",
    }


def generate_payment_events(
    registry: dict[str, Source],
    minimum_records: int,
    output_path: str | Path,
    seed: int = 42,
) -> dict[str, Any]:
    if minimum_records < 100:
        raise ValueError("minimum_records must be at least 100")
    sources = [source for source in registry.values() if source.mode in {"stream", "cdc"}]
    if not sources:
        raise ValueError("registry has no lifecycle sources")
    # Determinism is required for reproducible synthetic evidence; this PRNG never protects data.
    rng = random.Random(seed)  # nosec B311
    base = datetime(2026, 1, 1, tzinfo=UTC)
    valid: list[dict[str, Any]] = []
    transaction_number = 1
    while len(valid) < minimum_records:
        source = sources[(transaction_number - 1) % len(sources)]
        amount = 10_000 + (transaction_number * 7919) % 490_000
        transaction_events = [
            _event(
                transaction_number=transaction_number,
                version=1,
                event_type="authorization",
                amount_minor=amount,
                source=source,
                base_time=base + timedelta(seconds=transaction_number * 10),
            ),
            _event(
                transaction_number=transaction_number,
                version=2,
                event_type="capture",
                amount_minor=amount,
                source=source,
                base_time=base + timedelta(seconds=transaction_number * 10),
            ),
        ]
        if transaction_number % 5 == 0:
            transaction_events.append(
                _event(
                    transaction_number=transaction_number,
                    version=3,
                    event_type="refund",
                    amount_minor=max(1, amount // 4),
                    source=source,
                    base_time=base + timedelta(seconds=transaction_number * 10),
                )
            )
        elif transaction_number % 7 == 0:
            transaction_events.append(
                _event(
                    transaction_number=transaction_number,
                    version=3,
                    event_type="chargeback",
                    amount_minor=max(1, amount // 5),
                    source=source,
                    base_time=base + timedelta(seconds=transaction_number * 10),
                )
            )
        valid.extend(transaction_events)
        transaction_number += 1

    arrivals = list(valid)
    rng.shuffle(arrivals)
    injected: Counter[str] = Counter()
    for index in range(0, min(len(valid), max(4, len(valid) // 300)), 2):
        arrivals.append(dict(valid[index]))
        injected["exact_duplicates"] += 1

    conflict = dict(valid[0])
    conflict["amount_minor"] += 1
    conflict["received_at"] = (
        datetime.fromisoformat(conflict["received_at"]) + timedelta(minutes=5)
    ).isoformat()
    arrivals.append(conflict)
    injected["identity_conflicts"] += 1

    invalid_amount = dict(valid[1])
    invalid_amount["event_id"] = "fixture:invalid-amount"
    invalid_amount["transaction_id"] = "fixture:invalid-amount"
    invalid_amount["amount_minor"] = -100
    arrivals.append(invalid_amount)
    injected["invalid_amount"] += 1

    unsupported = dict(valid[1])
    unsupported["event_id"] = "fixture:unsupported-schema"
    unsupported["transaction_id"] = "fixture:unsupported-schema"
    unsupported["schema_version"] = "9.9"
    arrivals.append(unsupported)
    injected["unsupported_schema"] += 1

    prohibited = dict(valid[1])
    prohibited["event_id"] = "fixture:prohibited-pan"
    prohibited["transaction_id"] = "fixture:prohibited-pan"
    prohibited["card_number"] = "4111111111111111"
    arrivals.append(prohibited)
    injected["prohibited_fields"] += 1

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as stream:
        for event in arrivals:
            stream.write(json.dumps(event, separators=(",", ":"), sort_keys=True) + "\n")
    return {
        "classification": "SYNTHETIC_FIXTURE",
        "seed": seed,
        "raw_records": len(arrivals),
        "valid_unique_events": len(valid),
        "transactions": transaction_number - 1,
        "injected": dict(injected),
    }


def lifecycle_violation_fixture(registry: dict[str, Source]) -> list[dict[str, Any]]:
    source = next(source for source in registry.values() if source.mode == "stream")
    base = datetime(2026, 2, 1, tzinfo=UTC)
    capture = _event(
        transaction_number=999_999,
        version=1,
        event_type="capture",
        amount_minor=50_000,
        source=source,
        base_time=base,
    )
    capture["event_id"] = "fixture:capture-without-authorization"
    capture["transaction_id"] = "fixture:lifecycle-violation"
    return [capture]


def unique_crash_fixture(registry: dict[str, Source]) -> list[dict[str, Any]]:
    source = next(source for source in registry.values() if source.mode == "stream")
    base = datetime(2026, 3, 1, tzinfo=UTC)
    return [
        _event(
            transaction_number=888_888,
            version=1,
            event_type="authorization",
            amount_minor=75_000,
            source=source,
            base_time=base,
        ),
        _event(
            transaction_number=888_888,
            version=2,
            event_type="capture",
            amount_minor=75_000,
            source=source,
            base_time=base,
        ),
    ]
