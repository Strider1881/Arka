"""Evidence pack helpers for the proof report."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.models import Evidence


def collect_evidence(evidence_dir: str | Path) -> list[Evidence]:
    root = Path(evidence_dir)
    if not root.exists():
        return []
    items: list[Evidence] = []
    for path in sorted(root.glob("*.png")):
        items.append(Evidence(id=path.stem, label=path.stem, path=str(path), kind="screenshot"))
    return items
