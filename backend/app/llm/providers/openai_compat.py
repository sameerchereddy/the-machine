"""
Handles all OpenAI-compatible providers:
  - OpenAI
  - xAI (Grok)       — same API, different base_url
  - Ollama           — same API, local base_url
  - Custom           — any OpenAI-compatible endpoint
  - Azure OpenAI     — same SDK, different client class
"""

import json
from collections.abc import AsyncGenerator
from typing import Any

import openai

from ..adapter import BaseProvider
from ..types import LLMResponse, StreamChunk, ToolCall, Usage


class OpenAICompatProvider(BaseProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        self.model = config["model"]
        self.provider = config["provider"]
        self.client = openai.AsyncOpenAI(
            api_key=config.get("api_key", "ollama"),  # ollama ignores the key
            base_url=config.get("base_url"),  # None → OpenAI default
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        response = await self.client.chat.completions.create(**kwargs)
        choice = response.choices[0]
        msg = choice.message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            usage=Usage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            ),
            model=response.model,
            provider=self.provider,
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]:
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=True,
            stream_options={"include_usage": True},
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        tool_calls_acc: dict[int, dict[str, Any]] = {}

        async with await self.client.chat.completions.create(**kwargs) as stream:
            async for chunk in stream:
                if not chunk.choices:
                    if chunk.usage:
                        yield StreamChunk(
                            usage=Usage(
                                prompt_tokens=chunk.usage.prompt_tokens,
                                completion_tokens=chunk.usage.completion_tokens,
                                total_tokens=chunk.usage.total_tokens,
                            )
                        )
                    continue

                choice = chunk.choices[0]
                delta = choice.delta

                if delta.content:
                    yield StreamChunk(delta=delta.content)

                if delta.tool_calls:
                    for tc_delta in delta.tool_calls:
                        idx = tc_delta.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                        if tc_delta.id:
                            tool_calls_acc[idx]["id"] = tc_delta.id
                        if tc_delta.function and tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function and tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments

                if choice.finish_reason:
                    tool_calls = [
                        ToolCall(
                            id=acc["id"],
                            name=acc["name"],
                            arguments=json.loads(acc["arguments"]) if acc["arguments"] else {},
                        )
                        for acc in tool_calls_acc.values()
                    ]
                    yield StreamChunk(
                        finish_reason=choice.finish_reason,
                        tool_calls=tool_calls,
                    )

    async def embed(self, texts: list[str]) -> list[list[float]]:
        response = await self.client.embeddings.create(
            model="text-embedding-3-small",
            input=texts,
        )
        return [item.embedding for item in response.data]


class AzureProvider(OpenAICompatProvider):
    """Azure OpenAI — same SDK, different client constructor."""

    def __init__(self, config: dict[str, Any]) -> None:
        self.model = config["deployment_name"]
        self.provider = "azure"
        self.client = openai.AsyncAzureOpenAI(
            api_key=config["api_key"],
            azure_endpoint=config["base_url"],
            api_version=config.get("api_version", "2024-02-01"),
        )
