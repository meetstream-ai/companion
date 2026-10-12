"""
Password hashing.

Uses bcrypt directly rather than through passlib. passlib has been unmaintained
since 2020 and its bcrypt backend detection breaks against bcrypt 4.1+, which
surfaced as "no backends available" on a clean install - a failure a new
contributor would hit the first time they created an account.

bcrypt only looks at the first 72 bytes of its input. Passwords are therefore
pre-hashed with SHA-256 (base64, 44 bytes) so every byte of a long passphrase
counts; before this, "<first 72 bytes>" + anything verified. Hashes created by
older versions (plain bcrypt over the truncated password) still verify through
the legacy path and are upgraded on the next successful login.
"""
from __future__ import annotations

import base64
import hashlib

import bcrypt

#: bcrypt's hard input limit - the reason for the pre-hash.
BCRYPT_INPUT_LIMIT = 72

DEFAULT_ROUNDS = 12

#: Marker prefix distinguishing pre-hashed entries from legacy plain-bcrypt
#: ones. bcrypt strings always start with "$2"; this cannot collide.
PREHASH_PREFIX = "sha256$"


def _prehash(password: str) -> bytes:
    return base64.b64encode(hashlib.sha256(password.encode("utf-8")).digest())


def _legacy_encode(password: str) -> bytes:
    return password.encode("utf-8")[:BCRYPT_INPUT_LIMIT]


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("Password must not be empty.")
    digest = bcrypt.hashpw(_prehash(password), bcrypt.gensalt(rounds=DEFAULT_ROUNDS)).decode("utf-8")
    return PREHASH_PREFIX + digest


def verify_password(password: str, password_hash: str | None) -> bool:
    """Constant-time check that never raises on malformed stored hashes."""
    if not password or not password_hash:
        return False
    try:
        if password_hash.startswith(PREHASH_PREFIX):
            return bcrypt.checkpw(_prehash(password), password_hash[len(PREHASH_PREFIX):].encode("utf-8"))
        # Legacy hash from before the pre-hash: verify the way it was created.
        return bcrypt.checkpw(_legacy_encode(password), password_hash.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def needs_rehash(password_hash: str | None) -> bool:
    """True for legacy hashes, so a successful login can upgrade them."""
    return bool(password_hash) and not password_hash.startswith(PREHASH_PREFIX)
