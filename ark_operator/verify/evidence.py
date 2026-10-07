"""Evidence pack helpers for the proof report."""

from __future__ import annotations

from pathlib import Path

from ark_operator.domain.models import Evidence


def collect_evidence(evidence_dir: str | Path) -> list[Evidence]:
    root = Path(evidence_dir)
    if not root.exists():
        return []
    items: list[Evidence] = []
    for path in sorted(root.rglob("*.png")):
        items.append(Evidence(id=path.stem, label=path.stem, path=str(path), kind="screenshot"))
    return items


def collect_run_evidence(*dirs: str | Path) -> list[Evidence]:
    """Merge evidence screenshots from executor + verifier directories."""
    seen: set[str] = set()
    out: list[Evidence] = []
    for d in dirs:
        for item in collect_evidence(d):
            if item.path in seen:
                continue
            seen.add(item.path)
            out.append(item)
    return out
