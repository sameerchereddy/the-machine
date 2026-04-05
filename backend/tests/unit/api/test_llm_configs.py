"""
Unit tests for LLM config endpoints.
DB (asyncpg) and encryption are mocked — no real network calls.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_USER_ID = "00000000-0000-0000-0000-000000000001"
_CONFIG_ID = str(uuid.uuid4())

_VALID_COOKIE = {"access_token": "valid-tok"}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_current_user():
    return patch(
        "app.core.deps.verify_token",
        return_value={"id": _USER_ID, "email": "test@example.com"},
    )


def _make_db_row(config_id: str = _CONFIG_ID) -> MagicMock:
    row = MagicMock()
    row.__getitem__ = lambda self, key: {  # type: ignore[misc]
        "id": uuid.UUID(config_id),
        "name": "My OpenAI",
        "provider": "openai",
        "model": "gpt-4o",
        "is_default": False,
        "supports_tool_calls": True,
        "context_window": 128000,
        "config_enc": b"fake-enc",
        "config_iv": b"fake-iv",
    }[key]
    return row


_FAKE_CONFIG = {"api_key": "sk-test-1234567890"}


def _make_txn():
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    return txn


# ---------------------------------------------------------------------------
# List
# ---------------------------------------------------------------------------

class TestListConfigs:
    def test_returns_empty_list(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.get("/api/llm-configs", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert r.json() == []

    def test_returns_configs_with_masked_key(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetch.return_value = [row]

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG):
            r = client.get("/api/llm-configs", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        data = r.json()
        assert len(data) == 1
        assert "••••" in data[0]["config"]["api_key"]
        assert "sk-t" in data[0]["config"]["api_key"]

    def test_unauthenticated_returns_401(self) -> None:
        r = client.get("/api/llm-configs")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreateConfig:
    def test_creates_config(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row
        conn.transaction = MagicMock(return_value=_make_txn())

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.encrypt", return_value=(b"enc", b"iv")):
            r = client.post(
                "/api/llm-configs",
                json={
                    "name": "My OpenAI",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "config": {"api_key": "sk-test-1234567890"},
                },
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 201

    def test_create_response_masks_api_key(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row
        conn.transaction = MagicMock(return_value=_make_txn())

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.encrypt", return_value=(b"enc", b"iv")):
            r = client.post(
                "/api/llm-configs",
                json={
                    "name": "My OpenAI",
                    "provider": "openai",
                    "model": "gpt-4o",
                    "config": {"api_key": "sk-test-1234567890"},
                },
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 201
        assert "••••" in r.json()["config"]["api_key"]

    def test_unknown_provider_returns_422(self) -> None:
        with _mock_current_user():
            r = client.post(
                "/api/llm-configs",
                json={"name": "Bad", "provider": "notareal", "model": "x", "config": {}},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self) -> None:
        r = client.post(
            "/api/llm-configs",
            json={"name": "x", "provider": "openai", "model": "y", "config": {}},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Get
# ---------------------------------------------------------------------------

class TestGetConfig:
    def test_returns_config(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG):
            r = client.get(f"/api/llm-configs/{_CONFIG_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert r.json()["provider"] == "openai"

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.get(f"/api/llm-configs/{_CONFIG_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.get("/api/llm-configs/not-a-uuid", cookies=_VALID_COOKIE)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Patch
# ---------------------------------------------------------------------------

class TestUpdateConfig:
    def test_partial_update_name(self) -> None:
        row = _make_db_row()
        updated_row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [row, updated_row]
        conn.transaction = MagicMock(return_value=_make_txn())

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG):
            r = client.patch(
                f"/api/llm-configs/{_CONFIG_ID}",
                json={"name": "Renamed"},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 200

    def test_set_default_propagates(self) -> None:
        row = _make_db_row()
        updated_row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [row, updated_row]
        conn.transaction = MagicMock(return_value=_make_txn())

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG):
            r = client.patch(
                f"/api/llm-configs/{_CONFIG_ID}",
                json={"is_default": True},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 200
        # Should have cleared other defaults
        conn.execute.assert_called_once()

    def test_update_config_re_encrypts(self) -> None:
        row = _make_db_row()
        updated_row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [row, updated_row]
        conn.transaction = MagicMock(return_value=_make_txn())

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.encrypt", return_value=(b"new-enc", b"new-iv")) as mock_enc, \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG):
            r = client.patch(
                f"/api/llm-configs/{_CONFIG_ID}",
                json={"config": {"api_key": "sk-new-key-0000000000"}},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 200
        mock_enc.assert_called_once()

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.patch(
                f"/api/llm-configs/{_CONFIG_ID}",
                json={"name": "x"},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.patch(
                "/api/llm-configs/not-a-uuid",
                json={"name": "x"},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDeleteConfig:
    def test_deletes_config(self) -> None:
        conn = AsyncMock()
        conn.execute.return_value = "DELETE 1"

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.delete(f"/api/llm-configs/{_CONFIG_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 204

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.execute.return_value = "DELETE 0"

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.delete(f"/api/llm-configs/{_CONFIG_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.delete("/api/llm-configs/not-a-uuid", cookies=_VALID_COOKIE)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Ping (credentials direct — no DB)
# ---------------------------------------------------------------------------

class TestPingCredentials:
    def test_ping_success(self) -> None:
        with _mock_current_user(), \
             patch("app.api.llm_configs._ping_provider", new=AsyncMock(return_value=38.0)):
            r = client.post(
                "/api/llm-configs/ping",
                json={"provider": "openai", "model": "gpt-4o", "config": {"api_key": "sk-test"}},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 200
        assert r.json()["ok"] is True
        assert r.json()["latency_ms"] == pytest.approx(38.0)

    def test_ping_failure_returns_ok_false(self) -> None:
        with _mock_current_user(), \
             patch("app.api.llm_configs._ping_provider", new=AsyncMock(side_effect=Exception("bad key"))):
            r = client.post(
                "/api/llm-configs/ping",
                json={"provider": "openai", "model": "gpt-4o", "config": {"api_key": "bad"}},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_unknown_provider_returns_422(self) -> None:
        with _mock_current_user():
            r = client.post(
                "/api/llm-configs/ping",
                json={"provider": "notreal", "model": "x", "config": {}},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 422

    def test_unauthenticated_returns_401(self) -> None:
        r = client.post(
            "/api/llm-configs/ping",
            json={"provider": "openai", "model": "gpt-4o", "config": {}},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Ping (saved config by ID)
# ---------------------------------------------------------------------------

class TestPingConfig:
    def test_ping_success(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG), \
             patch("app.api.llm_configs._ping_provider", new=AsyncMock(return_value=42.5)):
            r = client.post(f"/api/llm-configs/{_CONFIG_ID}/ping", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert data["latency_ms"] == pytest.approx(42.5)

    def test_ping_failure_returns_ok_false(self) -> None:
        row = _make_db_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn), \
             patch("app.api.llm_configs.decrypt", return_value=_FAKE_CONFIG), \
             patch("app.api.llm_configs._ping_provider", new=AsyncMock(side_effect=Exception("bad key"))):
            r = client.post(f"/api/llm-configs/{_CONFIG_ID}/ping", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert r.json()["ok"] is False

    def test_ping_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), \
             patch("app.api.llm_configs._get_conn", return_value=conn):
            r = client.post(f"/api/llm-configs/{_CONFIG_ID}/ping", cookies=_VALID_COOKIE)

        assert r.status_code == 404
