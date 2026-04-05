from collections.abc import AsyncGenerator
from typing import Any

import google.generativeai as genai

from ..adapter import BaseProvider
from ..types import LLMResponse, StreamChunk, ToolCall, Usage


class GeminiProvider(BaseProvider):
    def __init__(self, config: dict[str, Any]) -> None:
        self.model_name = config["model"]
        genai.configure(api_key=config["api_key"])

    # ------------------------------------------------------------------
    # Format converters
    # ------------------------------------------------------------------

    def _convert_tools(self, tools: list[dict[str, Any]]) -> list[Any]:
        """Convert OpenAI function-calling format → Gemini Tool objects."""
        from google.generativeai.types import FunctionDeclaration, Tool

        declarations = [
            FunctionDeclaration(
                name=t["function"]["name"],
                description=t["function"].get("description", ""),
                parameters=t["function"].get("parameters", {}),
            )
            for t in tools
        ]
        return [Tool(function_declarations=declarations)]

    def _convert_messages(self, messages: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        """
        Split system prompt out and convert remaining messages to Gemini format.
        Returns (system_instruction, gemini_history).
        """
        system = ""
        history: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            elif msg["role"] == "user":
                history.append({"role": "user", "parts": [msg["content"]]})
            elif msg["role"] == "assistant":
                history.append({"role": "model", "parts": [msg["content"]]})
        return system, history

    def _make_model(self, system: str) -> Any:
        return genai.GenerativeModel(
            self.model_name,
            system_instruction=system or None,
        )

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
        system, history = self._convert_messages(messages)
        model = self._make_model(system)
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        kwargs: dict[str, Any] = {"generation_config": generation_config}
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        chat = model.start_chat(history=history[:-1])
        last_msg = history[-1]["parts"][0] if history else ""
        response = await chat.send_message_async(last_msg, **kwargs)

        content = ""
        tool_calls = []
        for part in response.parts:
            if hasattr(part, "text") and part.text:
                content += part.text
            elif hasattr(part, "function_call"):
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=fc.name,
                        name=fc.name,
                        arguments=dict(fc.args),
                    )
                )

        meta = response.usage_metadata
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                prompt_tokens=meta.prompt_token_count,
                completion_tokens=meta.candidates_token_count,
                total_tokens=meta.total_token_count,
            ),
            model=self.model_name,
            provider="gemini",
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]:
        system, history = self._convert_messages(messages)
        model = self._make_model(system)
        generation_config = genai.GenerationConfig(
            temperature=temperature,
            max_output_tokens=max_tokens,
        )
        kwargs: dict[str, Any] = {"generation_config": generation_config}
        if tools:
            kwargs["tools"] = self._convert_tools(tools)

        chat = model.start_chat(history=history[:-1])
        last_msg = history[-1]["parts"][0] if history else ""

        tool_calls: list[ToolCall] = []
        async for chunk in await chat.send_message_async(last_msg, stream=True, **kwargs):
            for part in chunk.parts:
                if hasattr(part, "text") and part.text:
                    yield StreamChunk(delta=part.text)
                elif hasattr(part, "function_call"):
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=fc.name,
                            name=fc.name,
                            arguments=dict(fc.args),
                        )
                    )

        if tool_calls:
            yield StreamChunk(finish_reason="tool_calls", tool_calls=tool_calls)

    async def embed(self, texts: list[str]) -> list[list[float]]:
        results = []
        for text in texts:
            response = await genai.embed_content_async(
                model="models/text-embedding-004",
                content=text,
            )
            results.append(response["embedding"])
        return results
