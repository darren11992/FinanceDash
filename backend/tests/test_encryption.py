"""
Tests for the Fernet encryption service.

Verifies:
- Round-trip: encrypt then decrypt returns the original value
- Different plaintexts produce different ciphertexts
- Ciphertext is URL-safe base64 (Fernet spec)
- Tampering with ciphertext raises an error
- Empty string round-trips correctly
- Long tokens round-trip correctly
"""

import pytest
from cryptography.fernet import InvalidToken

from app.services.encryption import decrypt_token, encrypt_token


class TestEncryptDecrypt:
    """Round-trip encryption/decryption tests."""

    def test_round_trip_basic(self):
        """Encrypting then decrypting returns the original plaintext."""
        plaintext = "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.test-access-token"
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext

    def test_round_trip_empty_string(self):
        """Empty string encrypts and decrypts correctly."""
        ciphertext = encrypt_token("")
        assert decrypt_token(ciphertext) == ""

    def test_round_trip_long_token(self):
        """Long token (simulating a real JWT) round-trips correctly."""
        # Real TrueLayer tokens are ~1000+ chars
        plaintext = "a" * 2000
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext

    def test_round_trip_unicode(self):
        """Unicode content round-trips correctly."""
        plaintext = "token-with-special-chars-£€¥"
        ciphertext = encrypt_token(plaintext)
        assert decrypt_token(ciphertext) == plaintext

    def test_ciphertext_differs_from_plaintext(self):
        """Ciphertext should not equal the plaintext."""
        plaintext = "my-secret-token"
        ciphertext = encrypt_token(plaintext)
        assert ciphertext != plaintext

    def test_different_plaintexts_produce_different_ciphertexts(self):
        """Two different plaintexts should produce different ciphertexts."""
        ct1 = encrypt_token("token-one")
        ct2 = encrypt_token("token-two")
        assert ct1 != ct2

    def test_same_plaintext_produces_different_ciphertexts(self):
        """Fernet uses a random IV, so encrypting the same value twice
        should produce different ciphertexts."""
        ct1 = encrypt_token("same-token")
        ct2 = encrypt_token("same-token")
        assert ct1 != ct2
        # Both should still decrypt to the same value
        assert decrypt_token(ct1) == decrypt_token(ct2) == "same-token"

    def test_ciphertext_is_url_safe_base64(self):
        """Fernet ciphertext should only contain URL-safe base64 characters."""
        import re
        ciphertext = encrypt_token("test-token")
        # Fernet tokens are URL-safe base64: [A-Za-z0-9_-]+ with = padding
        assert re.fullmatch(r"[A-Za-z0-9_=-]+", ciphertext), (
            f"Ciphertext contains non-base64 characters: {ciphertext}"
        )


class TestDecryptFailures:
    """Tests that decryption fails appropriately on bad input."""

    def test_tampered_ciphertext_raises(self):
        """Modifying the ciphertext should cause decryption to fail."""
        ciphertext = encrypt_token("original-token")
        # Flip a character in the middle of the ciphertext
        tampered = list(ciphertext)
        mid = len(tampered) // 2
        tampered[mid] = "A" if tampered[mid] != "A" else "B"
        tampered_str = "".join(tampered)

        with pytest.raises(InvalidToken):
            decrypt_token(tampered_str)

    def test_garbage_input_raises(self):
        """Completely invalid ciphertext should raise InvalidToken."""
        with pytest.raises(Exception):  # InvalidToken or binascii.Error
            decrypt_token("this-is-not-a-valid-fernet-token")

    def test_empty_ciphertext_raises(self):
        """Empty string as ciphertext should raise an error.
        Note: empty string != encrypted empty string."""
        with pytest.raises(Exception):
            decrypt_token("")
