"""
AES-256-GCM envelope encryption for LLM credentials.

Key derivation: HMAC-SHA256(SERVER_SECRET, user_id)
Each encrypt call generates a random 12-byte nonce (IV).
"""
import hashlib
import hmac
import json
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.config import settings


def _derive_key(user_id: str) -> bytes:
    """Derive a 32-byte AES key from SERVER_SECRET and user_id."""
    secret = settings.server_secret.encode()
    return hmac.new(secret, user_id.encode(), hashlib.sha256).digest()


def encrypt(data: dict[str, object], user_id: str) -> tuple[bytes, bytes]:
    """
    Encrypt a dict as JSON using AES-256-GCM.

    Returns:
        (ciphertext_with_tag, nonce)  — both stored in the DB.
    """
    key = _derive_key(user_id)
    nonce = os.urandom(12)
    aesgcm = AESGCM(key)
    plaintext = json.dumps(data).encode()
    ciphertext = aesgcm.encrypt(nonce, plaintext, None)
    return ciphertext, nonce


def decrypt(ciphertext: bytes, nonce: bytes, user_id: str) -> dict[str, object]:
    """
    Decrypt AES-256-GCM ciphertext back to a dict.

    Raises:
        cryptography.exceptions.InvalidTag  — if key/nonce/data is wrong.
    """
    key = _derive_key(user_id)
    aesgcm = AESGCM(key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    result: dict[str, object] = json.loads(plaintext)
    return result
