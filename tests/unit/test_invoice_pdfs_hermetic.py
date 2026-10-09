"""A5: invoice PDF generation is byte-stable across runs (clean checkout after setup)."""

from __future__ import annotations

from pathlib import Path

from company_world.scripts.make_invoices import generate_all


def test_generate_all_is_byte_identical(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    paths_a = generate_all(a)
    paths_b = generate_all(b)
    assert len(paths_a) == 12
    for pa, pb in zip(paths_a, paths_b, strict=True):
        assert pa.name == pb.name
        assert pa.read_bytes() == pb.read_bytes(), pa.name
