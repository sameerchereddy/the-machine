"""
Unit tests for the LLM provider adapter.

Tests cover:
- build_adapter factory routing (correct provider class selected)
- ProviderWithRetry retry logic (retries on transient errors, stops at max)
- ProviderWithRetry fallback (falls back when primary exhausts retries)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.llm.adapter import ProviderWithRetry, build_adapter, get_provider
from app.llm.types import LLMResponse, Usage


def _make_response(content: str = "hello") -> LLMResponse:
    return LLMResponse(
        content=content,
        tool_calls=[],
        usage=Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="gpt-4o-mini",
        provider="openai",
    )


class TestGetProvider:
    def test_openai_routes_to_openai_compat(self) -> None:
        from app.llm.providers.openai_compat import OpenAICompatProvider

        provider = get_provider({"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"})
        assert isinstance(provider, OpenAICompatProvider)

    def test_anthropic_routes_to_anthropic_provider(self) -> None:
        from app.llm.providers.anthropic import AnthropicProvider

        provider = get_provider({"provider": "anthropic", "api_key": "sk-ant-test", "model": "claude-3-haiku-20240307"})
        assert isinstance(provider, AnthropicProvider)

    def test_unknown_provider_raises(self) -> None:
        with pytest.raises(ValueError, match="Unknown provider"):
            get_provider({"provider": "doesnotexist", "api_key": "x", "model": "x"})


class TestProviderWithRetry:
    @pytest.mark.asyncio
    async def test_returns_on_first_success(self) -> None:
        primary = MagicMock()
        primary.complete = AsyncMock(return_value=_make_response("ok"))
        adapter = ProviderWithRetry(primary=primary, fallback=None, max_retries=2, timeout_seconds=5)

        result = await adapter.complete(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "ok"
        primary.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_retries_on_transient_error(self) -> None:
        primary = MagicMock()
        primary.complete = AsyncMock(
            side_effect=[RuntimeError("timeout"), _make_response("retry worked")]
        )
        adapter = ProviderWithRetry(primary=primary, fallback=None, max_retries=2, timeout_seconds=5)

        result = await adapter.complete(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "retry worked"
        assert primary.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_falls_back_after_exhausted_retries(self) -> None:
        primary = MagicMock()
        primary.complete = AsyncMock(side_effect=RuntimeError("always fails"))
        fallback = MagicMock()
        fallback.complete = AsyncMock(return_value=_make_response("from fallback"))
        adapter = ProviderWithRetry(primary=primary, fallback=fallback, max_retries=1, timeout_seconds=5)

        result = await adapter.complete(messages=[{"role": "user", "content": "hi"}])
        assert result.content == "from fallback"
        fallback.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_raises_when_no_fallback_and_retries_exhausted(self) -> None:
        primary = MagicMock()
        primary.complete = AsyncMock(side_effect=RuntimeError("always fails"))
        adapter = ProviderWithRetry(primary=primary, fallback=None, max_retries=1, timeout_seconds=5)

        with pytest.raises(RuntimeError, match="always fails"):
            await adapter.complete(messages=[{"role": "user", "content": "hi"}])


class TestBuildAdapter:
    def test_returns_provider_with_retry(self) -> None:
        config = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"}
        adapter = build_adapter(config)
        assert isinstance(adapter, ProviderWithRetry)

    def test_fallback_is_none_when_not_provided(self) -> None:
        config = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"}
        adapter = build_adapter(config)
        assert adapter.fallback is None

    def test_fallback_is_set_when_provided(self) -> None:
        primary = {"provider": "openai", "api_key": "sk-test", "model": "gpt-4o-mini"}
        fallback = {"provider": "anthropic", "api_key": "sk-ant-test", "model": "claude-3-haiku-20240307"}
        adapter = build_adapter(primary, fallback)
        assert adapter.fallback is not None
