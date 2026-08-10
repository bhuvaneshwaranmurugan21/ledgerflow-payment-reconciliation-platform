"""LedgerFlow command-line interface."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ledgerflow.evidence import PROFILE_RECORDS, run_evidence


def project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _evidence(args: argparse.Namespace) -> int:
    raw_key = os.environ.get("LEDGERFLOW_TOKEN_KEY")
    if raw_key is None:
        raise SystemExit("LEDGERFLOW_TOKEN_KEY is required and must contain at least 32 characters")
    output = Path(args.output).resolve()
    summary = run_evidence(
        root=project_root(),
        output=output,
        profile=args.profile,
        token_key=raw_key.encode("utf-8"),
        seed=args.seed,
    )
    measured = summary["measured_local"]
    result = {
        "classification": summary["classification"],
        "profile": args.profile,
        "raw_records": measured["raw_records"],
        "ledger_entries": measured["ledger_entry"],
        "ledger_balanced": measured["ledger_balanced"],
        "replay_ledger_delta": measured["replay_ledger_delta"],
        "failure_scenarios": (
            f"{summary['failure_lab']['passed']}/{summary['failure_lab']['scenario_count']}"
        ),
        "evidence": str(output / "summary.json"),
    }
    print(json.dumps(result, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="LedgerFlow financial-correctness platform")
    commands = parser.add_subparsers(dest="command", required=True)
    evidence = commands.add_parser("evidence", help="run measured local evidence suite")
    evidence.add_argument("--profile", choices=sorted(PROFILE_RECORDS), default="smoke")
    evidence.add_argument("--output", required=True)
    evidence.add_argument("--seed", type=int, default=42)
    evidence.set_defaults(handler=_evidence)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.handler(args))
