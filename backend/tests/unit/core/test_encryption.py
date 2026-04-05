"""Unit tests for AES-256-GCM encryption helpers."""
import pytest
from unittest.mock import patch

# Patch settings before importing encryption so the module-level settings load works
_FAKE_SETTINGS_ATTRS = {
    "server_secret": "a" * 32,
    "supabase_url": "https://fake.supabase.co",
    "supabase_anon_key": "fake-anon",
    "supabase_service_key": "fake-service",
    "storage_bucket": "knowledge",
    "database_url": None,
    "allowed_origins": ["http://localhost:5173"],
}


class _FakeSettings:
    def __getattr__(self, name):  # type: ignore[override]
        if name in _FAKE_SETTINGS_ATTRS:
            return _FAKE_SETTINGS_ATTRS[name]
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _patch_settings():
    with patch("app.core.encryption.settings", _FakeSettings()):
        yield


from app.core.encryption import decrypt, encrypt  # noqa: E402


USER_A = "00000000-0000-0000-0000-000000000001"
USER_B = "00000000-0000-0000-0000-000000000002"


def test_round_trip():
    data = {"api_key": "sk-test-1234", "base_url": "https://api.openai.com"}
    ciphertext, nonce = encrypt(data, USER_A)
    recovered = decrypt(ciphertext, nonce, USER_A)
    assert recovered == data


def test_nonce_is_random():
    data = {"api_key": "same"}
    _, nonce1 = encrypt(data, USER_A)
    _, nonce2 = encrypt(data, USER_A)
    assert nonce1 != nonce2  # Each call uses a fresh nonce


def test_different_users_cannot_decrypt_each_others_data():
    from cryptography.exceptions import InvalidTag

    data = {"api_key": "secret"}
    ciphertext, nonce = encrypt(data, USER_A)
    with pytest.raises(InvalidTag):
        decrypt(ciphertext, nonce, USER_B)


def test_tampered_ciphertext_raises():
    from cryptography.exceptions import InvalidTag

    data = {"x": 1}
    ciphertext, nonce = encrypt(data, USER_A)
    tampered = bytes([ciphertext[0] ^ 0xFF]) + ciphertext[1:]
    with pytest.raises(InvalidTag):
        decrypt(tampered, nonce, USER_A)


def test_complex_nested_dict():
    data = {
        "api_key": "sk-abc",
        "nested": {"a": 1, "b": [1, 2, 3]},
        "unicode": "héllo wörld",
    }
    ciphertext, nonce = encrypt(data, USER_A)
    assert decrypt(ciphertext, nonce, USER_A) == data
