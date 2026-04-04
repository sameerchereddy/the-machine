import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator
from typing import Any

from .types import LLMResponse, StreamChunk

logger = logging.getLogger(__name__)


class BaseProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse: ...

    @abstractmethod
    def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]: ...

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError(f"{self.__class__.__name__} does not support embeddings")


class ProviderWithRetry:
    """
    Wraps any BaseProvider with retry, timeout, and fallback logic.
    This is the object the agent loop uses — it never touches a raw provider directly.
    """

    def __init__(
        self,
        primary: BaseProvider,
        fallback: BaseProvider | None = None,
        max_retries: int = 2,
        timeout_seconds: int = 30,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.max_retries = max_retries
        self.timeout_seconds = timeout_seconds

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> LLMResponse:
        result: LLMResponse = await self._with_retry_and_fallback(
            "complete", messages, tools=tools, **kwargs
        )
        return result

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncGenerator[StreamChunk, None]:
        last_exc: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            try:
                async for chunk in self.primary.stream(messages, tools=tools, **kwargs):
                    yield chunk
                return
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries and self._is_retryable(exc):
                    logger.warning(f"Stream attempt {attempt + 1} failed ({exc}), retrying...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                break

        if self.fallback:
            logger.warning(f"Primary stream failed, switching to fallback. Error: {last_exc}")
            async for chunk in self.fallback.stream(messages, tools=tools, **kwargs):
                yield chunk
        else:
            assert last_exc is not None
            raise last_exc

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return await self.primary.embed(texts)

    async def _with_retry_and_fallback(self, method: str, *args: Any, **kwargs: Any) -> Any:
        last_exc: BaseException | None = None

        for attempt in range(self.max_retries + 1):
            try:
                return await asyncio.wait_for(
                    getattr(self.primary, method)(*args, **kwargs),
                    timeout=self.timeout_seconds,
                )
            except Exception as exc:
                last_exc = exc
                if attempt < self.max_retries and self._is_retryable(exc):
                    logger.warning(f"Attempt {attempt + 1} failed ({exc}), retrying...")
                    await asyncio.sleep(2 ** attempt)
                    continue
                break

        if self.fallback:
            logger.warning(
                f"Primary failed after {self.max_retries} retries, "
                f"switching to fallback. Error: {last_exc}"
            )
            return await getattr(self.fallback, method)(*args, **kwargs)

        assert last_exc is not None
        raise last_exc

    def _is_retryable(self, exc: Exception) -> bool:
        """Retry on all transient errors. Non-retryable exceptions (e.g. auth failures)
        should be raised by the provider before reaching here."""
        return True


def get_provider(config: dict[str, Any]) -> BaseProvider:
    """Return the correct BaseProvider for the given decrypted config dict."""
    provider = config["provider"]

    if provider in ("openai", "grok", "ollama", "custom"):
        from .providers.openai_compat import OpenAICompatProvider
        return OpenAICompatProvider(config)
    elif provider == "azure":
        from .providers.openai_compat import AzureProvider
        return AzureProvider(config)
    elif provider == "anthropic":
        from .providers.anthropic import AnthropicProvider
        return AnthropicProvider(config)
    elif provider == "gemini":
        from .providers.gemini import GeminiProvider
        return GeminiProvider(config)
    elif provider == "bedrock":
        from .providers.bedrock import BedrockProvider
        return BedrockProvider(config)
    else:
        raise ValueError(f"Unknown provider: '{provider}'")


def build_adapter(
    primary_config: dict[str, Any],
    fallback_config: dict[str, Any] | None = None,
) -> ProviderWithRetry:
    """
    Build a ProviderWithRetry from decrypted config dicts.
    This is the main entry point — call this from the agent and API layers.

    Example:
        adapter = build_adapter(decrypted_primary, decrypted_fallback)
        response = await adapter.complete(messages, tools=tools)
    """
    primary = get_provider(primary_config)
    fallback = get_provider(fallback_config) if fallback_config else None
    return ProviderWithRetry(
        primary=primary,
        fallback=fallback,
        max_retries=primary_config.get("max_retries", 2),
        timeout_seconds=primary_config.get("timeout_seconds", 30),
    )
