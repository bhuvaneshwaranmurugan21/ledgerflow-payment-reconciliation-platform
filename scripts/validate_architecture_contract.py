"""Fail when an internal architecture box has no retained implementation artifact."""

from __future__ import annotations

import json
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    manifest = json.loads((root / "docs" / "architecture-manifest.json").read_text())
    diagram = root / manifest["diagram"]
    if not diagram.is_file():
        raise SystemExit(f"missing canonical architecture diagram: {diagram}")
    ids: set[str] = set()
    failures: list[str] = []
    for component in manifest["components"]:
        component_id = component["id"]
        if component_id in ids:
            failures.append(f"duplicate component: {component_id}")
        ids.add(component_id)
        if component["boundary"] not in {"internal", "external"}:
            failures.append(f"invalid boundary: {component_id}")
        artifacts = component.get("artifacts", [])
        if not artifacts:
            failures.append(f"component has no artifacts: {component_id}")
        for artifact in artifacts:
            if not (root / artifact).is_file():
                failures.append(f"{component_id}: missing {artifact}")
    if failures:
        raise SystemExit("\n".join(failures))
    print(f"validated {len(ids)} architecture components against retained artifacts")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
