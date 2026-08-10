from __future__ import annotations

import json
from pathlib import Path

import pytest

from ledgerflow import cli


def test_cli_prints_classified_evidence_summary(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    fake_summary = {
        "classification": "MEASURED_LOCAL_RESULT",
        "measured_local": {
            "raw_records": 100,
            "ledger_entry": 120,
            "ledger_balanced": True,
            "replay_ledger_delta": 0,
        },
        "failure_lab": {"passed": 15, "scenario_count": 15},
    }

    def fake_run_evidence(**_kwargs: object) -> dict[str, object]:
        return fake_summary

    monkeypatch.setattr(cli, "run_evidence", fake_run_evidence)
    monkeypatch.setenv("LEDGERFLOW_TOKEN_KEY", "synthetic-key-with-at-least-32-characters")
    monkeypatch.setattr(
        "sys.argv", ["ledgerflow", "evidence", "--profile", "smoke", "--output", str(tmp_path)]
    )
    assert cli.main() == 0
    output = json.loads(capsys.readouterr().out)
    assert output["classification"] == "MEASURED_LOCAL_RESULT"
    assert output["failure_scenarios"] == "15/15"


def test_cli_requires_token_key(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("LEDGERFLOW_TOKEN_KEY", raising=False)
    parser = cli.build_parser()
    args = parser.parse_args(["evidence", "--output", str(tmp_path)])
    with pytest.raises(SystemExit, match="LEDGERFLOW_TOKEN_KEY is required"):
        args.handler(args)
