"""Reject public claims without a classification and retained evidence path."""

from __future__ import annotations

import json
from pathlib import Path

ALLOWED = {
    "MEASURED_LOCAL_RESULT",
    "VERIFIED_IMPLEMENTATION_PROPERTY",
    "MODELED_PRODUCTION_CAPACITY",
    "EVIDENCE_BOUNDARY",
}


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    registry = json.loads((root / "docs" / "claims.json").read_text())
    failures: list[str] = []
    for index, claim in enumerate(registry.get("claims", []), start=1):
        if claim.get("classification") not in ALLOWED:
            failures.append(f"claim {index}: unsupported classification")
        if not claim.get("statement"):
            failures.append(f"claim {index}: missing statement")
        evidence = claim.get("evidence", [])
        if not evidence:
            failures.append(f"claim {index}: no evidence")
        for path in evidence:
            if not (root / path).is_file():
                failures.append(f"claim {index}: missing {path}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"validated {len(registry['claims'])} classified public claims")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
