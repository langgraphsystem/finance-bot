"""Token encryption helpers using Fernet symmetric encryption."""

import logging
import os

from cryptography.fernet import Fernet

logger = logging.getLogger(__name__)

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is not None:
        return _fernet

    key = os.environ.get("OAUTH_ENCRYPTION_KEY", "")
    if not key:
        raise ValueError(
            "OAUTH_ENCRYPTION_KEY env var is required for token encryption. "
            'Generate one with: python -c "from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    _fernet = Fernet(key if isinstance(key, bytes) else key.encode())
    return _fernet


def encrypt_token(plaintext: str) -> bytes:
    """Encrypt an OAuth token for storage."""
    return _get_fernet().encrypt(plaintext.encode())


def decrypt_token(ciphertext: bytes) -> str:
    """Decrypt an OAuth token from storage."""
    return _get_fernet().decrypt(ciphertext).decode()
