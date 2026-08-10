from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerflow.manifest import ManifestError, build_manifest, verify_manifest


def test_manifest_verifies_checksum_count_and_control_total(tmp_path: Path) -> None:
    data = tmp_path / "events.jsonl"
    rows = [
        {"event_id": "a", "amount_minor": 100, "currency": "INR"},
        {"event_id": "b", "amount_minor": 50, "currency": "INR"},
        {"event_id": "c", "amount_minor": 75, "currency": "USD"},
    ]
    data.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    manifest_path = tmp_path / "events.manifest.json"
    manifest = build_manifest(data, manifest_path)
    verified = verify_manifest(data, manifest_path)
    assert verified["sha256"] == manifest["sha256"]
    assert verified["record_count"] == 3
    assert verified["raw_control_totals_minor"] == {"INR": 150, "USD": 75}


def test_manifest_blocks_tampering_before_ingestion(tmp_path: Path) -> None:
    data = tmp_path / "events.jsonl"
    data.write_text('{"event_id":"a","amount_minor":100,"currency":"INR"}\n')
    manifest_path = tmp_path / "events.manifest.json"
    build_manifest(data, manifest_path)
    data.write_text(data.read_text() + '{"event_id":"b","amount_minor":1,"currency":"INR"}\n')
    with pytest.raises(ManifestError, match="manifest_byte_size_mismatch"):
        verify_manifest(data, manifest_path)
