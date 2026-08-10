from __future__ import annotations

from pathlib import Path

from ledgerflow.evidence import run_evidence
from tests.conftest import ROOT, TOKEN_KEY


def test_complete_evidence_suite_passes(tmp_path: Path) -> None:
    summary = run_evidence(
        root=ROOT,
        output=tmp_path / "evidence",
        profile="smoke",
        token_key=TOKEN_KEY,
        seed=42,
    )
    failure_lab = summary["failure_lab"]
    measured = summary["measured_local"]
    assert failure_lab["failed"] == 0
    assert failure_lab["passed"] == failure_lab["scenario_count"] == 15
    assert measured["ledger_balanced"] is True
    assert measured["replay_ledger_delta"] == 0
    assert measured["replay_state_unchanged"] is True
    assert (tmp_path / "evidence" / "summary.json").is_file()
    assert (tmp_path / "evidence" / "report.html").is_file()
