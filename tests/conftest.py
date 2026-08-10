from __future__ import annotations

from pathlib import Path

import pytest

from ledgerflow.contracts import Source, load_source_registry
from ledgerflow.ledger import PostingRules, load_posting_rules

ROOT = Path(__file__).resolve().parents[1]
TOKEN_KEY = b"synthetic-test-token-key-at-least-32-bytes"


@pytest.fixture
def registry() -> dict[str, Source]:
    return load_source_registry(ROOT / "config" / "sources.json")


@pytest.fixture
def posting_rules() -> PostingRules:
    return load_posting_rules(ROOT / "config" / "posting_rules.json")
