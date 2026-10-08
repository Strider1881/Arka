"""Password hashing for portal users (demo-grade PBKDF2; not plaintext)."""

from __future__ import annotations

import hashlib
import hmac
import secrets

_PREFIX = "pbkdf2_sha256"
_ITERATIONS = 120_000


def hash_password(password: str, *, salt: str | None = None) -> str:
    """Return a stored hash string: pbkdf2_sha256$iterations$salt$hexdigest."""
    salt_hex = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt_hex.encode("utf-8"),
        _ITERATIONS,
    )
    return f"{_PREFIX}${_ITERATIONS}${salt_hex}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    """Constant-time verify. Accepts legacy plaintext only when stored has no $ prefix."""
    if not stored:
        return False
    if stored.startswith(f"{_PREFIX}$"):
        try:
            _algo, iters_s, salt_hex, digest_hex = stored.split("$", 3)
            iters = int(iters_s)
        except ValueError:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt_hex.encode("utf-8"),
            iters,
        )
        return hmac.compare_digest(digest.hex(), digest_hex)
    # Legacy plaintext rows (pre-hash seed) — demo migrate path only.
    return hmac.compare_digest(password, stored)
