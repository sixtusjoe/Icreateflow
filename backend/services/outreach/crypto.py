"""Symmetric encryption for stored browser session state.

Sending-account sessions (Playwright `storage_state` — cookies plus local
storage) are the closest thing this pipeline has to a credential, so they
never touch the database in the clear.

Key material comes from `ICREATE_OUTREACH_SECRET` when set, otherwise it
is derived from `ICREATE_JWT_SECRET` so an existing deployment works with
no new environment variable. Rotating either one makes previously stored
sessions undecryptable — `decrypt_session` returns None and the account is
paused with `session_expired` rather than crashing the worker.

`cryptography` is already an installed dependency (python-jose[cryptography]).
"""
from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken


class SessionCryptoUnavailable(RuntimeError):
    """No key material configured — refuse to store a session in the clear."""


def _key() -> bytes:
    secret = os.environ.get("ICREATE_OUTREACH_SECRET") or os.environ.get("ICREATE_JWT_SECRET")
    if not secret:
        raise SessionCryptoUnavailable(
            "Set ICREATE_OUTREACH_SECRET (or ICREATE_JWT_SECRET) before storing "
            "sending-account sessions."
        )
    # Fernet wants 32 url-safe base64 bytes; the app secrets are arbitrary
    # length hex, so hash them down deterministically.
    digest = hashlib.sha256(f"outreach-session::{secret}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_session(plaintext: str) -> str:
    """Encrypt a session blob. Raises SessionCryptoUnavailable with no key."""
    return Fernet(_key()).encrypt(plaintext.encode()).decode()


def decrypt_session(ciphertext: Optional[str]) -> Optional[str]:
    """Decrypt a session blob, or None if absent / unreadable.

    Unreadable covers both a rotated key and a corrupted value; the caller
    treats both as "this account needs a fresh session".
    """
    if not ciphertext:
        return None
    try:
        return Fernet(_key()).decrypt(ciphertext.encode()).decode()
    except (InvalidToken, SessionCryptoUnavailable, ValueError, TypeError):
        return None


def crypto_available() -> bool:
    try:
        _key()
        return True
    except SessionCryptoUnavailable:
        return False
