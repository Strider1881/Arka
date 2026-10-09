"""Load numeric policy parameters from company knowledge markdown (SSoT).

``rules.yaml`` keeps tool permissions / risk mapping only. Threshold and
tolerance come from ``approval_policy.md`` and ``tolerance_policy.md``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_KNOWLEDGE_DIR = Path(__file__).resolve().parents[2] / "company_world" / "knowledge"


@dataclass(frozen=True)
class PolicyParams:
    approval_threshold_usd: float
    tolerance_pct: float
    blocked_vendors: frozenset[str]
    vendor_aliases: dict[str, str]
    sources: dict[str, str]


_THRESHOLD_RE = re.compile(
    r"greater than\s+\$([0-9][0-9,]*(?:\.[0-9]+)?)\s*USD",
    re.IGNORECASE,
)
_TOLERANCE_RE = re.compile(
    r"at most\s+\*\*([0-9]+(?:\.[0-9]+)?)\s*%",
    re.IGNORECASE,
)
_BLOCKED_RE = re.compile(
    r"\*\*([^*]+)\*\*\s+is\s+`?BLOCKED`?",
    re.IGNORECASE,
)
_ALIAS_ROW_RE = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*$",
    re.MULTILINE,
)


def _money(raw: str) -> float:
    return float(raw.replace(",", ""))


def load_policy_params(knowledge_dir: Path | None = None) -> PolicyParams:
    """Parse threshold / tolerance / blocked / aliases from knowledge markdown."""
    root = knowledge_dir or DEFAULT_KNOWLEDGE_DIR
    approval = (root / "approval_policy.md").read_text(encoding="utf-8")
    tolerance = (root / "tolerance_policy.md").read_text(encoding="utf-8")
    vendor = (root / "vendor_policy.md").read_text(encoding="utf-8")

    thr_m = _THRESHOLD_RE.search(approval)
    if not thr_m:
        raise ValueError(f"approval threshold not found in {root / 'approval_policy.md'}")
    threshold = _money(thr_m.group(1))

    tol_m = _TOLERANCE_RE.search(tolerance)
    if not tol_m:
        raise ValueError(f"tolerance pct not found in {root / 'tolerance_policy.md'}")
    tolerance_pct = float(tol_m.group(1))

    blocked = {m.group(1).strip() for m in _BLOCKED_RE.finditer(vendor)}
    aliases: dict[str, str] = {}
    in_alias_table = False
    for line in vendor.splitlines():
        if line.strip().startswith("| Alias"):
            in_alias_table = True
            continue
        if in_alias_table:
            if not line.strip().startswith("|"):
                break
            if re.match(r"^\|\s*-+", line):
                continue
            row = _ALIAS_ROW_RE.match(line)
            if row:
                aliases[row.group(1).strip()] = row.group(2).strip()

    return PolicyParams(
        approval_threshold_usd=threshold,
        tolerance_pct=tolerance_pct,
        blocked_vendors=frozenset(blocked),
        vendor_aliases=aliases,
        sources={
            "approval_threshold_usd": "approval_policy.md",
            "tolerance_pct": "tolerance_policy.md",
            "blocked_vendors": "vendor_policy.md",
            "vendor_aliases": "vendor_policy.md",
        },
    )


def assert_rules_permissions_only(rules: dict) -> None:
    """Fail closed if rules.yaml still embeds KB-owned numeric params."""
    forbidden = {"approval_threshold_usd", "tolerance_pct", "blocked_vendors", "vendor_aliases"}
    present = sorted(k for k in forbidden if k in rules)
    if present:
        raise ValueError(
            "rules.yaml must be permissions-only; move these to knowledge markdown: "
            + ", ".join(present)
        )
