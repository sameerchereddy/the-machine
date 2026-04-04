import json
from collections.abc import AsyncGenerator
from typing import Any

import anthropic

from ..adapter import BaseProvider
from ..types import LLMResponse, StreamChunk, ToolCall, Usage


class AnthropicProvider(BaseProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        self.model = config["model"]
        self.client = anthropic.AsyncAnthropic(api_key=config["api_key"])

    # ------------------------------------------------------------------
    # Format converters
    # ------------------------------------------------------------------

    def _split_system(
        self, messages: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Anthropic requires the system prompt as a top-level param, not in messages."""
        system = ""
        rest = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                rest.append(msg)
        return system, rest

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Convert OpenAI function-calling format → Anthropic tool format."""
        return [
            {
                "name": t["function"]["name"],
                "description": t["function"].get("description", ""),
                "input_schema": t["function"].get(
                    "parameters", {"type": "object", "properties": {}}
                ),
            }
            for t in tools
        ]

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> LLMResponse:
        system, msgs = self._split_system(messages)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        response = await self.client.messages.create(**kwargs)

        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content = block.text
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                prompt_tokens=response.usage.input_tokens,
                completion_tokens=response.usage.output_tokens,
                total_tokens=response.usage.input_tokens + response.usage.output_tokens,
            ),
            model=response.model,
            provider="anthropic",
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]:
        system, msgs = self._split_system(messages)
        kwargs: dict[str, Any] = dict(
            model=self.model,
            messages=msgs,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        tool_calls_acc: dict[str, dict[str, Any]] = {}

        async with self.client.messages.stream(**kwargs) as stream:
            async for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        idx = str(event.index)
                        tool_calls_acc[idx] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "arguments": "",
                        }

                elif event.type == "content_block_delta":
                    if event.delta.type == "text_delta":
                        yield StreamChunk(delta=event.delta.text)
                    elif event.delta.type == "input_json_delta":
                        idx = str(event.index)
                        if idx in tool_calls_acc:
                            tool_calls_acc[idx]["arguments"] += event.delta.partial_json

                elif event.type == "message_delta" and event.delta.stop_reason:
                    tool_calls = [
                        ToolCall(
                            id=acc["id"],
                            name=acc["name"],
                            arguments=json.loads(acc["arguments"]) if acc["arguments"] else {},
                        )
                        for acc in tool_calls_acc.values()
                    ]
                    usage = getattr(event, "usage", None)
                    yield StreamChunk(
                        finish_reason=event.delta.stop_reason,
                        tool_calls=tool_calls,
                        usage=Usage(
                            prompt_tokens=usage.input_tokens,
                            completion_tokens=usage.output_tokens,
                            total_tokens=usage.input_tokens + usage.output_tokens,
                        ) if usage else None,
                    )
