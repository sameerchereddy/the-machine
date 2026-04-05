"""
Unit tests for agent CRUD + tools endpoints.
DB is mocked — no real network calls.
"""

import uuid
from datetime import UTC
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)

_USER_ID = "00000000-0000-0000-0000-000000000001"
_AGENT_ID = str(uuid.uuid4())
_TOOL_ID = str(uuid.uuid4())

_VALID_COOKIE = {"access_token": "valid-tok"}


def _mock_current_user():
    return patch(
        "app.core.deps.verify_token",
        return_value={"id": _USER_ID, "email": "test@example.com"},
    )


def _make_agent_row(agent_id: str = _AGENT_ID) -> MagicMock:
    row = MagicMock()
    data: dict = {
        "id": uuid.UUID(agent_id),
        "name": "Test Agent",
        "llm_config_id": None,
        "instructions": "",
        "persona_name": None,
        "response_style": "balanced",
        "output_format": "markdown",
        "output_schema": None,
        "response_language": "en",
        "show_reasoning": False,
        "context_entries": [],
        "auto_inject_datetime": True,
        "auto_inject_user_profile": True,
        "context_render_as": "yaml",
        "history_window": 20,
        "summarise_old_messages": False,
        "long_term_enabled": False,
        "memory_types": ["preferences", "facts"],
        "max_memories": 100,
        "retention_days": 90,
        "kb_top_k": 4,
        "kb_similarity_threshold": 0.7,
        "kb_reranking": False,
        "kb_show_sources": True,
        "kb_chunk_size": 512,
        "kb_chunk_overlap": 64,
        "max_iterations": 5,
        "on_max_iterations": "return_partial",
        "max_tool_calls_per_run": 20,
        "max_tokens_per_run": 8000,
        "topic_restrictions": [],
        "allow_clarifying_questions": True,
        "pii_detection": False,
        "safe_tool_mode": False,
    }
    row.__getitem__ = lambda self, key: data[key]  # type: ignore[misc]
    return row


def _make_tool_row(tool_id: str = _TOOL_ID) -> MagicMock:
    row = MagicMock()
    data: dict = {
        "id": uuid.UUID(tool_id),
        "agent_id": uuid.UUID(_AGENT_ID),
        "tool_key": "web_search",
        "name": "Web Search",
        "description": "Search the web",
        "parameters": {},
        "enabled": True,
        "timeout_seconds": 15,
        "max_calls_per_run": 5,
        "retry_on_failure": True,
        "show_result_in_chat": True,
        "result_truncation_chars": 2000,
        "credentials_enc": None,
        "credentials_iv": None,
        "endpoint_url": None,
        "sort_order": 0,
    }
    row.__getitem__ = lambda self, key: data[key]  # type: ignore[misc]
    return row


def _make_txn():
    txn = MagicMock()
    txn.__aenter__ = AsyncMock(return_value=None)
    txn.__aexit__ = AsyncMock(return_value=False)
    return txn


# ---------------------------------------------------------------------------
# Agents — Create
# ---------------------------------------------------------------------------


class TestCreateAgent:
    def test_creates_agent_with_defaults(self) -> None:
        row = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.post(
                "/api/agents",
                json={"name": "Test Agent"},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 201
        assert r.json()["name"] == "Test Agent"

    def test_foreign_llm_config_id_returns_404(self) -> None:
        """Cannot create agent with another user's llm_config_id."""
        conn = AsyncMock()
        # First fetchrow is the ownership check — returns None (not found/not owned)
        conn.fetchrow.return_value = None

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.post(
                "/api/agents",
                json={"name": "Bad", "llm_config_id": str(uuid.uuid4())},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 404

    def test_unauthenticated_returns_401(self) -> None:
        r = client.post("/api/agents", json={"name": "x"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Agents — List
# ---------------------------------------------------------------------------


class TestListAgents:
    def test_returns_empty_list(self) -> None:
        conn = AsyncMock()
        conn.fetch.return_value = []

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get("/api/agents", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert r.json() == []

    def test_returns_agent_summaries(self) -> None:
        from datetime import datetime

        summary = MagicMock()
        summary.__getitem__ = lambda self, key: {  # type: ignore[misc]
            "id": uuid.UUID(_AGENT_ID),
            "name": "Test Agent",
            "llm_config_id": None,
            "created_at": datetime.now(UTC),
            "updated_at": datetime.now(UTC),
        }[key]

        conn = AsyncMock()
        conn.fetch.return_value = [summary]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get("/api/agents", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["name"] == "Test Agent"

    def test_unauthenticated_returns_401(self) -> None:
        r = client.get("/api/agents")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Agents — Get
# ---------------------------------------------------------------------------


class TestGetAgent:
    def test_returns_agent(self) -> None:
        row = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = row

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get(f"/api/agents/{_AGENT_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert r.json()["id"] == _AGENT_ID

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get(f"/api/agents/{_AGENT_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.get("/api/agents/not-a-uuid", cookies=_VALID_COOKIE)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Agents — Update
# ---------------------------------------------------------------------------


class TestUpdateAgent:
    def test_updates_name(self) -> None:
        row = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [row, row]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.put(
                f"/api/agents/{_AGENT_ID}",
                json={"name": "Renamed"},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 200

    def test_explicit_null_llm_config_id_clears_it(self) -> None:
        """Sending llm_config_id: null explicitly should detach the LLM."""
        existing = _make_agent_row()
        updated = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [existing, updated]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.put(
                f"/api/agents/{_AGENT_ID}",
                json={"name": "Test Agent", "llm_config_id": None},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 200
        # The UPDATE call should have been made with None for llm_config_id
        call_args = conn.fetchrow.call_args_list[1]
        assert call_args[0][2] is None  # $2 is llm_config_id in the UPDATE

    def test_foreign_llm_config_id_returns_404(self) -> None:
        """Cannot update agent with another user's llm_config_id."""
        existing = _make_agent_row()
        conn = AsyncMock()
        # First fetchrow: get existing agent (found), second: ownership check (not found)
        conn.fetchrow.side_effect = [existing, None]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.put(
                f"/api/agents/{_AGENT_ID}",
                json={"name": "x", "llm_config_id": str(uuid.uuid4())},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 404

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.put(
                f"/api/agents/{_AGENT_ID}",
                json={"name": "x"},
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.put(
                "/api/agents/not-a-uuid",
                json={"name": "x"},
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Agents — Delete
# ---------------------------------------------------------------------------


class TestDeleteAgent:
    def test_deletes_agent(self) -> None:
        conn = AsyncMock()
        conn.execute.return_value = "DELETE 1"

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.delete(f"/api/agents/{_AGENT_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 204

    def test_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.execute.return_value = "DELETE 0"

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.delete(f"/api/agents/{_AGENT_ID}", cookies=_VALID_COOKIE)

        assert r.status_code == 404

    def test_invalid_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.delete("/api/agents/not-a-uuid", cookies=_VALID_COOKIE)
        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tools — List
# ---------------------------------------------------------------------------


class TestListTools:
    def test_returns_tools(self) -> None:
        agent_row = _make_agent_row()
        tool_row = _make_tool_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = agent_row
        conn.fetch.return_value = [tool_row]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get(f"/api/agents/{_AGENT_ID}/tools", cookies=_VALID_COOKIE)

        assert r.status_code == 200
        assert len(r.json()) == 1
        assert r.json()[0]["tool_key"] == "web_search"

    def test_agent_not_found_returns_404(self) -> None:
        conn = AsyncMock()
        conn.fetchrow.return_value = None

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.get(f"/api/agents/{_AGENT_ID}/tools", cookies=_VALID_COOKIE)

        assert r.status_code == 404


# ---------------------------------------------------------------------------
# Tools — Add
# ---------------------------------------------------------------------------


class TestAddTool:
    def test_adds_tool(self) -> None:
        agent_row = _make_agent_row()
        tool_row = _make_tool_row()
        conn = AsyncMock()
        conn.fetchrow.side_effect = [agent_row, tool_row]

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.post(
                f"/api/agents/{_AGENT_ID}/tools",
                json={
                    "tool_key": "web_search",
                    "name": "Web Search",
                    "description": "Search the web",
                },
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 201
        assert r.json()["tool_key"] == "web_search"

    def test_unauthenticated_returns_401(self) -> None:
        r = client.post(
            f"/api/agents/{_AGENT_ID}/tools",
            json={"tool_key": "x", "name": "x", "description": "x"},
        )
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# Tools — Delete
# ---------------------------------------------------------------------------


class TestDeleteTool:
    def test_deletes_tool(self) -> None:
        agent_row = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = agent_row
        conn.execute.return_value = "DELETE 1"

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.delete(
                f"/api/agents/{_AGENT_ID}/tools/{_TOOL_ID}",
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 204

    def test_not_found_returns_404(self) -> None:
        agent_row = _make_agent_row()
        conn = AsyncMock()
        conn.fetchrow.return_value = agent_row
        conn.execute.return_value = "DELETE 0"

        with _mock_current_user(), patch("app.api.agents._get_conn", return_value=conn):
            r = client.delete(
                f"/api/agents/{_AGENT_ID}/tools/{_TOOL_ID}",
                cookies=_VALID_COOKIE,
            )

        assert r.status_code == 404

    def test_invalid_agent_uuid_returns_404(self) -> None:
        with _mock_current_user():
            r = client.delete(
                f"/api/agents/not-a-uuid/tools/{_TOOL_ID}",
                cookies=_VALID_COOKIE,
            )
        assert r.status_code == 404
