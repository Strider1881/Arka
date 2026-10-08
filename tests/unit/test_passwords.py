"""Portal password hashing (not plaintext)."""

from __future__ import annotations

from company_world.portal.passwords import hash_password, verify_password


def test_hash_and_verify() -> None:
    stored = hash_password("secret-pass")
    assert stored.startswith("pbkdf2_sha256$")
    assert "secret-pass" not in stored
    assert verify_password("secret-pass", stored)
    assert not verify_password("wrong", stored)


def test_legacy_plaintext_verify() -> None:
    assert verify_password("plain", "plain")
    assert not verify_password("plain", "other")
