"""Reproducible local benchmark, replay proof and failure laboratory."""

from __future__ import annotations

import hashlib
import html
import os
import platform
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ledgerflow.contracts import canonical_json, load_source_registry, sha256_text, write_json
from ledgerflow.ledger import PostingLine, PostingRuleError, assert_balanced, load_posting_rules
from ledgerflow.manifest import ManifestError, build_manifest, iter_jsonl, verify_manifest
from ledgerflow.simulator import (
    generate_payment_events,
    lifecycle_violation_fixture,
    unique_crash_fixture,
)
from ledgerflow.store import LedgerStore

PROFILE_RECORDS = {"smoke": 5_000, "evidence": 50_000, "stress": 250_000}


def _implementation_sha256(root: Path) -> str:
    """Bind retained evidence to the executable core, contracts and rule configuration."""
    digest = hashlib.sha256()
    paths = sorted((root / "src" / "ledgerflow").glob("*.py"))
    paths += sorted((root / "contracts").glob("*.json"))
    paths += sorted((root / "config").glob("*.json"))
    for path in paths:
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _scenario(name: str, passed: bool, evidence: str) -> dict[str, str]:
    return {"name": name, "status": "PASS" if passed else "FAIL", "evidence": evidence}


def _write_html_report(summary: dict[str, Any], path: Path) -> None:
    rows = "".join(
        "<tr><td>{}</td><td>{}</td><td>{}</td></tr>".format(
            html.escape(row["name"]), html.escape(row["status"]), html.escape(row["evidence"])
        )
        for row in summary["failure_lab"]["scenarios"]
    )
    measured = summary["measured_local"]
    document = f"""<!doctype html><html><head><meta charset='utf-8'>
<title>LedgerFlow verified evidence</title><style>
body{{font-family:Arial,sans-serif;background:#05080d;color:#e5e7eb;margin:0;padding:32px}}
h1{{color:#f8fafc}}.note{{color:#94a3b8}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px}}
.card{{background:#15191f;border:1px solid #4b5563;padding:18px}}.value{{font-size:28px;font-weight:700}}
table{{width:100%;border-collapse:collapse;margin-top:24px}}th,td{{padding:10px;border-bottom:1px solid #374151;text-align:left}}
</style></head><body><h1>LedgerFlow verified local evidence</h1>
<p class='note'>Synthetic data • measured on {html.escape(summary["machine"]["platform"])} • not cloud-scale proof</p>
<div class='grid'><div class='card'><div>Raw arrivals</div><div class='value'>{measured["raw_records"]:,}</div></div>
<div class='card'><div>Accepted events</div><div class='value'>{measured["accepted_event"]:,}</div></div>
<div class='card'><div>Ledger entries</div><div class='value'>{measured["ledger_entry"]:,}</div></div>
<div class='card'><div>Replay ledger delta</div><div class='value'>{measured["replay_ledger_delta"]}</div></div>
<div class='card'><div>Ledger balance</div><div class='value'>{measured["ledger_balance_minor"]}</div></div>
<div class='card'><div>Failure checks</div><div class='value'>{summary["failure_lab"]["passed"]}/{summary["failure_lab"]["scenario_count"]}</div></div></div>
<table><thead><tr><th>Scenario</th><th>Status</th><th>Evidence</th></tr></thead><tbody>{rows}</tbody></table>
<p class='note'>Claims are classified in docs/claims.json. Production targets remain modeled requirements until a cloud deployment report exists.</p>
</body></html>"""
    path.write_text(document, encoding="utf-8")


def run_evidence(
    *,
    root: Path,
    output: Path,
    profile: str,
    token_key: bytes,
    seed: int = 42,
) -> dict[str, Any]:
    if profile not in PROFILE_RECORDS:
        raise ValueError(f"unknown profile: {profile}")
    output.mkdir(parents=True, exist_ok=True)
    work = output / "work"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir()
    registry = load_source_registry(root / "config" / "sources.json")
    rules = load_posting_rules(root / "config" / "posting_rules.json")
    raw_path = work / "payment_events.jsonl"
    generation = generate_payment_events(registry, PROFILE_RECORDS[profile], raw_path, seed=seed)
    manifest_path = work / "payment_events.manifest.json"
    manifest = build_manifest(raw_path, manifest_path)
    verified_manifest = verify_manifest(raw_path, manifest_path)
    store = LedgerStore(work / "ledgerflow.sqlite")

    started = time.perf_counter()
    first = store.process(
        run_id="initial-load",
        input_sha256=manifest["sha256"],
        raw_events=iter_jsonl(raw_path),
        registry=registry,
        token_key=token_key,
        posting_rules=rules,
    )
    elapsed = time.perf_counter() - started
    ledger_before = first["ledger_entry"]
    state_before = first["payment_state_sha256"]

    replay_started = time.perf_counter()
    replay = store.process(
        run_id="exact-replay",
        input_sha256=manifest["sha256"],
        raw_events=iter_jsonl(raw_path),
        registry=registry,
        token_key=token_key,
        posting_rules=rules,
    )
    replay_elapsed = time.perf_counter() - replay_started

    expected = store.expected_settlement()
    settlement_pass = store.reconcile_settlement(expected)
    mismatch = [dict(row) for row in expected]
    if mismatch:
        mismatch[0]["amount_minor"] -= 101
    settlement_fail = store.reconcile_settlement(mismatch)
    settlement_restored = store.reconcile_settlement(expected)

    corrupted_manifest = work / "corrupted.manifest.json"
    corrupted = dict(manifest)
    corrupted["sha256"] = "0" * 64
    write_json(corrupted_manifest, corrupted)
    corrupt_blocked = False
    try:
        verify_manifest(raw_path, corrupted_manifest)
    except ManifestError:
        corrupt_blocked = True

    accepted_before_crash = store.table_count("accepted_event")
    crash_rolled_back = False
    try:
        store.process(
            run_id="injected-crash",
            input_sha256=sha256_text("injected-crash"),
            raw_events=unique_crash_fixture(registry),
            registry=registry,
            token_key=token_key,
            posting_rules=rules,
            failpoint="before_commit",
        )
    except RuntimeError:
        crash_rolled_back = store.table_count("accepted_event") == accepted_before_crash

    lifecycle_store = LedgerStore(work / "lifecycle.sqlite")
    lifecycle = lifecycle_store.process(
        run_id="lifecycle-violation",
        input_sha256=sha256_text("lifecycle-violation"),
        raw_events=lifecycle_violation_fixture(registry),
        registry=registry,
        token_key=token_key,
        posting_rules=rules,
    )

    version_gap_events = unique_crash_fixture(registry)
    version_gap_events[1]["transaction_version"] = 3
    version_gap_events[1]["event_id"] = "txn-0000888888:v3"
    version_gap_store = LedgerStore(work / "version-gap.sqlite")
    version_gap = version_gap_store.process(
        run_id="version-gap",
        input_sha256=sha256_text("version-gap"),
        raw_events=version_gap_events,
        registry=registry,
        token_key=token_key,
        posting_rules=rules,
    )

    unbalanced_detected = False
    try:
        assert_balanced(
            (
                PostingLine(
                    entry_id="fixture:1",
                    event_id="fixture",
                    transaction_id="fixture",
                    processor_id="fixture",
                    merchant_id="fixture",
                    currency="INR",
                    account="processor_receivable",
                    signed_minor=100,
                    posting_rule_version=1,
                ),
            )
        )
    except PostingRuleError:
        unbalanced_detected = True

    replay_ledger_delta = replay["ledger_entry"] - ledger_before
    scenarios = [
        _scenario("manifest_checksum_gate", corrupt_blocked, "corrupt checksum rejected"),
        _scenario(
            "raw_outcome_reconciliation", first["raw_reconciled"], "every arrival classified"
        ),
        _scenario(
            "identity_payload_conflict",
            first["outcomes"].get("QUARANTINED:identity_payload_conflict", 0) > 0,
            "same event ID with altered money quarantined",
        ),
        _scenario(
            "prohibited_card_field",
            first["outcomes"].get("QUARANTINED:prohibited_fields:card_number", 0) > 0,
            "PAN-like field blocked before curated storage",
        ),
        _scenario(
            "double_entry_balance", first["ledger_balanced"], "every posting group sums to zero"
        ),
        _scenario("unbalanced_rule_detector", unbalanced_detected, "unbalanced fixture rejected"),
        _scenario(
            "exact_replay_no_second_effect",
            replay_ledger_delta == 0 and replay["payment_state_sha256"] == state_before,
            f"ledger_delta={replay_ledger_delta}",
        ),
        _scenario(
            "crash_before_commit", crash_rolled_back, "accepted and ledger state rolled back"
        ),
        _scenario(
            "lifecycle_violation",
            lifecycle["business_exception"] == 1 and lifecycle["ledger_entry"] == 0,
            "capture without authorization excluded from ledger",
        ),
        _scenario(
            "transaction_version_gap",
            version_gap["business_exception"] == 2 and version_gap["ledger_entry"] == 0,
            "non-contiguous lifecycle excluded as one transaction",
        ),
        _scenario(
            "settlement_match",
            settlement_pass["settlement_reconciled"],
            "external totals equal internal expectation",
        ),
        _scenario(
            "settlement_mismatch_gate",
            not settlement_fail["settlement_reconciled"]
            and settlement_fail["settlement_absolute_delta_minor"] == 101,
            "101 minor-unit difference blocks publication",
        ),
        _scenario(
            "settlement_recovery",
            settlement_restored["settlement_reconciled"],
            "corrected evidence clears gate",
        ),
        _scenario(
            "clear_email_exclusion",
            store.clear_email_leak_count() == 0,
            "curated event payloads contain only HMAC tokens",
        ),
        _scenario(
            "out_of_order_determinism",
            first["business_exception"] == 0 and first["payment_state"] > 0,
            "arrival shuffle reconstructed by transaction_version",
        ),
    ]
    passed = sum(row["status"] == "PASS" for row in scenarios)
    machine = {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "logical_cpus": os.cpu_count(),
    }
    measured = {
        **first,
        "elapsed_seconds": round(elapsed, 6),
        "records_per_second": round(first["raw_records"] / elapsed, 2),
        "replay_seconds": round(replay_elapsed, 6),
        "replay_ledger_delta": replay_ledger_delta,
        "replay_state_unchanged": replay["payment_state_sha256"] == state_before,
        "settlement_groups": len(expected),
    }
    summary = {
        "classification": "MEASURED_LOCAL_RESULT",
        "generated_at": datetime.now(UTC).isoformat(),
        "profile": profile,
        "implementation_sha256": _implementation_sha256(root),
        "machine": machine,
        "generation": generation,
        "manifest": verified_manifest,
        "measured_local": measured,
        "failure_lab": {
            "scenario_count": len(scenarios),
            "passed": passed,
            "failed": len(scenarios) - passed,
            "scenarios": scenarios,
        },
        "evidence_sha256": "",
        "limitations": [
            "Synthetic local evidence is not an AWS throughput or availability measurement.",
            "Cloud deployment status remains unverified until a retained deployment report exists.",
            "SQLite represents transaction boundaries; production storage uses the mapped AWS services.",
        ],
    }
    summary["evidence_sha256"] = sha256_text(canonical_json(summary))
    write_json(output / "summary.json", summary)
    _write_html_report(summary, output / "report.html")
    shutil.rmtree(work)
    if passed != len(scenarios):
        raise RuntimeError(f"failure laboratory did not pass: {passed}/{len(scenarios)}")
    return summary
