"""
Token encryption/decryption using Fernet (symmetric AES-128-CBC + HMAC).

TrueLayer access and refresh tokens are encrypted before writing to the
database and decrypted only in-memory when needed for API calls.

The encryption key is loaded from the TRUELAYER_TOKEN_ENCRYPTION_KEY
environment variable and must never be stored in the database or
committed to source control.

Sprint 2: Full implementation.
"""

from cryptography.fernet import Fernet

from app.config import settings

# Initialise the Fernet cipher once at module load.
_fernet = Fernet(settings.truelayer_token_encryption_key.encode())


def encrypt_token(plaintext: str) -> str:
    """Encrypt a plaintext token string. Returns a URL-safe base64 ciphertext."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a ciphertext token string back to plaintext."""
    return _fernet.decrypt(ciphertext.encode()).decode()
