"""Token encryption helpers using Fernet symmetric encryption."""

import os

from cryptography.fernet import Fernet


def _get_fernet() -> Fernet:
    key = os.environ.get("OAUTH_ENCRYPTION_KEY", "")
    if not key:
        key = Fernet.generate_key().decode()
    return Fernet(key if isinstance(key, bytes) else key.encode())


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt an OAuth token for storage."""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_token(ciphertext: bytes) -> str:
    """Decrypt an OAuth token from storage."""
    return _get_fernet().decrypt(ciphertext).decode()
