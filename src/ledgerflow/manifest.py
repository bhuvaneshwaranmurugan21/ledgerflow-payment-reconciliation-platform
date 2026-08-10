"""Manifest completeness, checksum and source-control-total verification."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast

from ledgerflow.contracts import write_json


class ManifestError(ValueError):
    """Raised before ingestion when immutable source evidence is incomplete."""


def iter_jsonl(path: str | Path) -> Iterator[dict[str, Any]]:
    with Path(path).open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            try:
                value = json.loads(line)
            except json.JSONDecodeError as error:
                raise ManifestError(f"invalid_json_line:{line_number}") from error
            if not isinstance(value, dict):
                raise ManifestError(f"non_object_line:{line_number}")
            yield value


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(data_path: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    source = Path(data_path)
    totals: dict[str, int] = defaultdict(int)
    records = 0
    for event in iter_jsonl(source):
        records += 1
        amount = event.get("amount_minor")
        currency = event.get("currency")
        if isinstance(amount, int) and not isinstance(amount, bool) and isinstance(currency, str):
            totals[currency] += amount
    manifest = {
        "version": 1,
        "file_name": source.name,
        "byte_size": source.stat().st_size,
        "record_count": records,
        "sha256": file_sha256(source),
        "raw_control_totals_minor": dict(sorted(totals.items())),
    }
    write_json(manifest_path, manifest)
    return manifest


def verify_manifest(data_path: str | Path, manifest_path: str | Path) -> dict[str, Any]:
    source = Path(data_path)
    manifest = cast(dict[str, Any], json.loads(Path(manifest_path).read_text(encoding="utf-8")))
    if manifest.get("file_name") != source.name:
        raise ManifestError("manifest_file_name_mismatch")
    if manifest.get("byte_size") != source.stat().st_size:
        raise ManifestError("manifest_byte_size_mismatch")
    if manifest.get("sha256") != file_sha256(source):
        raise ManifestError("manifest_checksum_mismatch")
    rebuilt_path = Path(manifest_path).with_suffix(".verification.tmp")
    try:
        actual = build_manifest(source, rebuilt_path)
    finally:
        rebuilt_path.unlink(missing_ok=True)
    if manifest.get("record_count") != actual["record_count"]:
        raise ManifestError("manifest_record_count_mismatch")
    if manifest.get("raw_control_totals_minor") != actual["raw_control_totals_minor"]:
        raise ManifestError("manifest_control_total_mismatch")
    return manifest
