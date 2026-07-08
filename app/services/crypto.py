"""Symmetric encryption for secrets (Telegram bot token, AI API key) stored
at rest in the `settings` table.

Fails loudly if no key is configured rather than silently falling back to a
derived/weak key — encryption of stored secrets should never depend on an
implicit default.
"""

from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class EncryptionNotConfigured(Exception):
    pass


@lru_cache
def _fernet() -> Fernet:
    key = get_settings().settings_encryption_key
    if not key:
        raise EncryptionNotConfigured(
            "SETTINGS_ENCRYPTION_KEY is not set. Generate one with:\n"
            '  python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"\n'
            "and set it in .env before storing secrets in Settings."
        )
    return Fernet(key.encode("utf-8"))


def encrypt(plaintext: str) -> str:
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise EncryptionNotConfigured(
            "Stored secret could not be decrypted — SETTINGS_ENCRYPTION_KEY is missing or changed."
        ) from exc
