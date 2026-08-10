"""Versioned double-entry posting rules and balance assertions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ledgerflow.contracts import EVENT_TYPES, PaymentEvent


class PostingRuleError(ValueError):
    """Raised when posting rules could create unbalanced financial effects."""


@dataclass(frozen=True)
class PostingLine:
    entry_id: str
    event_id: str
    transaction_id: str
    processor_id: str
    merchant_id: str
    currency: str
    account: str
    signed_minor: int
    posting_rule_version: int


@dataclass(frozen=True)
class PostingRules:
    version: int
    rules: dict[str, tuple[tuple[str, int], ...]]


def load_posting_rules(path: str | Path) -> PostingRules:
    raw: dict[str, Any] = json.loads(Path(path).read_text(encoding="utf-8"))
    if raw.get("currency_unit") != "minor":
        raise PostingRuleError("posting rules must use integer minor units")
    version = raw.get("version")
    if not isinstance(version, int) or version < 1:
        raise PostingRuleError("posting-rule version must be a positive integer")
    parsed: dict[str, tuple[tuple[str, int], ...]] = {}
    for event_type in EVENT_TYPES:
        lines = raw.get("rules", {}).get(event_type)
        if not isinstance(lines, list):
            raise PostingRuleError(f"missing posting rule: {event_type}")
        entries: list[tuple[str, int]] = []
        for line in lines:
            account = line.get("account")
            multiplier = line.get("multiplier")
            if not isinstance(account, str) or not account:
                raise PostingRuleError(f"invalid account for {event_type}")
            if isinstance(multiplier, bool) or not isinstance(multiplier, int):
                raise PostingRuleError(f"invalid multiplier for {event_type}")
            entries.append((account, multiplier))
        if sum(multiplier for _, multiplier in entries) != 0:
            raise PostingRuleError(f"unbalanced rule: {event_type}")
        parsed[event_type] = tuple(entries)
    return PostingRules(version=version, rules=parsed)


def build_postings(event: PaymentEvent, rules: PostingRules) -> tuple[PostingLine, ...]:
    lines = tuple(
        PostingLine(
            entry_id=f"{event.event_id}:{position}",
            event_id=event.event_id,
            transaction_id=event.transaction_id,
            processor_id=event.processor_id,
            merchant_id=event.merchant_id,
            currency=event.currency,
            account=account,
            signed_minor=event.amount_minor * multiplier,
            posting_rule_version=rules.version,
        )
        for position, (account, multiplier) in enumerate(rules.rules[event.event_type], start=1)
    )
    assert_balanced(lines)
    return lines


def assert_balanced(lines: tuple[PostingLine, ...]) -> None:
    grouped: dict[tuple[str, str], int] = {}
    for line in lines:
        key = (line.event_id, line.currency)
        grouped[key] = grouped.get(key, 0) + line.signed_minor
    unbalanced = {key: amount for key, amount in grouped.items() if amount != 0}
    if unbalanced:
        raise PostingRuleError(f"unbalanced posting group: {unbalanced}")
