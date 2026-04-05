import json
from collections.abc import AsyncGenerator
from typing import Any

import aiobotocore.session

from ..adapter import BaseProvider
from ..types import LLMResponse, StreamChunk, ToolCall, Usage


class BedrockProvider(BaseProvider):
    """
    AWS Bedrock via the Converse API — works uniformly across all Bedrock models
    (Claude, Llama, Titan, Mistral, etc.) without model-specific formatting.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self.model_id = config["model"]
        self.region = config.get("region", "us-east-1")
        self.aws_access_key = config["api_key"]  # api_key doubles as AWS access key
        self.aws_secret_key = config["aws_secret_key"]
        self._session = aiobotocore.session.get_session()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _client(self) -> Any:
        return self._session.create_client(
            "bedrock-runtime",
            region_name=self.region,
            aws_access_key_id=self.aws_access_key,
            aws_secret_access_key=self.aws_secret_key,
        )

    def _build_request(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None,
        temperature: float,
        max_tokens: int,
    ) -> dict[str, Any]:
        """Build a Converse API request body from OpenAI-format inputs."""
        system = ""
        msgs = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                msgs.append(
                    {
                        "role": msg["role"],
                        "content": [{"text": msg["content"]}],
                    }
                )

        body: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": msgs,
            "inferenceConfig": {
                "temperature": temperature,
                "maxTokens": max_tokens,
            },
        }
        if system:
            body["system"] = [{"text": system}]
        if tools:
            body["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["function"]["name"],
                            "description": t["function"].get("description", ""),
                            "inputSchema": {"json": t["function"].get("parameters", {})},
                        }
                    }
                    for t in tools
                ]
            }
        return body

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
        body = self._build_request(messages, tools, temperature, max_tokens)

        async with self._client() as client:
            response = await client.converse(**body)

        content = ""
        tool_calls = []
        for block in response["output"]["message"]["content"]:
            if "text" in block:
                content += block["text"]
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    ToolCall(
                        id=tu["toolUseId"],
                        name=tu["name"],
                        arguments=tu["input"],
                    )
                )

        usage = response["usage"]
        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            usage=Usage(
                prompt_tokens=usage["inputTokens"],
                completion_tokens=usage["outputTokens"],
                total_tokens=usage["totalTokens"],
            ),
            model=self.model_id,
            provider="bedrock",
        )

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
    ) -> AsyncGenerator[StreamChunk, None]:
        body = self._build_request(messages, tools, temperature, max_tokens)

        tool_calls_acc: dict[str, dict[str, Any]] = {}

        async with self._client() as client:
            response = await client.converse_stream(**body)
            async for event in response["stream"]:
                if "contentBlockDelta" in event:
                    delta = event["contentBlockDelta"]["delta"]
                    if "text" in delta:
                        yield StreamChunk(delta=delta["text"])
                    elif "toolUse" in delta:
                        idx = str(event["contentBlockDelta"]["contentBlockIndex"])
                        if idx in tool_calls_acc:
                            tool_calls_acc[idx]["arguments"] += delta["toolUse"].get("input", "")

                elif "contentBlockStart" in event:
                    block = event["contentBlockStart"].get("start", {})
                    if "toolUse" in block:
                        idx = str(event["contentBlockStart"]["contentBlockIndex"])
                        tool_calls_acc[idx] = {
                            "id": block["toolUse"]["toolUseId"],
                            "name": block["toolUse"]["name"],
                            "arguments": "",
                        }

                elif "messageStop" in event:
                    tool_calls = [
                        ToolCall(
                            id=acc["id"],
                            name=acc["name"],
                            arguments=json.loads(acc["arguments"]) if acc["arguments"] else {},
                        )
                        for acc in tool_calls_acc.values()
                    ]
                    yield StreamChunk(
                        finish_reason=event["messageStop"]["stopReason"],
                        tool_calls=tool_calls,
                    )

                elif "metadata" in event:
                    usage = event["metadata"].get("usage", {})
                    if usage:
                        yield StreamChunk(
                            usage=Usage(
                                prompt_tokens=usage.get("inputTokens", 0),
                                completion_tokens=usage.get("outputTokens", 0),
                                total_tokens=usage.get("totalTokens", 0),
                            )
                        )
