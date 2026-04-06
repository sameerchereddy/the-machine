"""
Unit tests for the ReAct agent loop.
LLM adapter and tools are mocked.
"""

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.loop import (
    RunTrace,
    build_system_prompt,
    msg_delta,
    msg_done,
    msg_error,
    msg_tool_end,
    msg_tool_start,
    run_react_loop,
)
from app.llm.types import LLMResponse, ToolCall, Usage

_USAGE = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)

_AGENT: dict[str, Any] = {
    "id": "00000000-0000-0000-0000-000000000001",
    "instructions": "You are a helpful assistant.",
    "persona_name": None,
    "auto_inject_datetime": False,
    "context_entries": [],
    "max_iterations": 5,
    "max_tool_calls_per_run": 20,
    "max_tokens_per_run": 8000,
    "on_max_iterations": "return_partial",
}

_LLM_CONFIG: dict[str, Any] = {
    "provider": "openai",
    "model": "gpt-4o-mini",
    "supports_tool_calls": True,
}


def _make_adapter(responses: list[LLMResponse]) -> MagicMock:
    adapter = MagicMock()
    adapter.complete = AsyncMock(side_effect=responses)
    return adapter


def _collect_sends() -> tuple[list[dict[str, Any]], AsyncMock]:
    sent: list[dict[str, Any]] = []

    async def send(msg: dict[str, Any]) -> None:
        sent.append(msg)

    return sent, send


# ---------------------------------------------------------------------------
# Message constructors
# ---------------------------------------------------------------------------


class TestMessageConstructors:
    def test_msg_delta(self) -> None:
        assert msg_delta("hello") == {"type": "delta", "content": "hello"}

    def test_msg_tool_start(self) -> None:
        m = msg_tool_start("id1", "calculator", {"expression": "2+2"})
        assert m["type"] == "tool_start"
        assert m["tool_name"] == "calculator"

    def test_msg_tool_end(self) -> None:
        m = msg_tool_end("id1", "4")
        assert m == {"type": "tool_end", "tool_id": "id1", "result": "4"}

    def test_msg_done(self) -> None:
        m = msg_done("trace-1", {"total_tokens": 100})
        assert m["type"] == "done"
        assert m["trace_id"] == "trace-1"

    def test_msg_error(self) -> None:
        assert msg_error("oops") == {"type": "error", "message": "oops"}


# ---------------------------------------------------------------------------
# System prompt builder
# ---------------------------------------------------------------------------


class TestBuildSystemPrompt:
    def test_uses_instructions(self) -> None:
        agent = dict(_AGENT, instructions="Be concise.")
        prompt = build_system_prompt(agent)
        assert "Be concise." in prompt

    def test_includes_persona(self) -> None:
        agent = dict(_AGENT, persona_name="Aria")
        prompt = build_system_prompt(agent)
        assert "Aria" in prompt

    def test_includes_context_entries(self) -> None:
        agent = dict(_AGENT, context_entries=[{"key": "user_role", "value": "admin"}])
        prompt = build_system_prompt(agent)
        assert "user_role" in prompt
        assert "admin" in prompt

    def test_includes_datetime_when_enabled(self) -> None:
        agent = dict(_AGENT, auto_inject_datetime=True)
        prompt = build_system_prompt(agent)
        assert "UTC" in prompt


# ---------------------------------------------------------------------------
# ReAct loop — direct response (no tool calls)
# ---------------------------------------------------------------------------


class TestLoopDirectResponse:
    @pytest.mark.asyncio
    async def test_streams_response(self) -> None:
        adapter = _make_adapter(
            [
                LLMResponse(
                    content="Hello world!",
                    tool_calls=[],
                    usage=_USAGE,
                    model="gpt-4o-mini",
                    provider="openai",
                )
            ]
        )
        sent, send = _collect_sends()
        stopped = asyncio.Event()

        trace = await run_react_loop(_AGENT, _LLM_CONFIG, adapter, "hi", send, stopped)

        delta_msgs = [m for m in sent if m["type"] == "delta"]
        full_text = "".join(m["content"] for m in delta_msgs)
        assert full_text == "Hello world!"
        assert trace.final_response == "Hello world!"
        assert trace.error is None

    @pytest.mark.asyncio
    async def test_sends_iteration_message(self) -> None:
        adapter = _make_adapter(
            [LLMResponse(content="Hi", tool_calls=[], usage=_USAGE, model="m", provider="p")]
        )
        sent, send = _collect_sends()
        stopped = asyncio.Event()

        await run_react_loop(_AGENT, _LLM_CONFIG, adapter, "hi", send, stopped)

        iteration_msgs = [m for m in sent if m["type"] == "iteration"]
        assert len(iteration_msgs) >= 1
        assert iteration_msgs[0]["n"] == 1

    @pytest.mark.asyncio
    async def test_stop_event_halts_streaming(self) -> None:
        adapter = _make_adapter(
            [LLMResponse(content="A" * 200, tool_calls=[], usage=_USAGE, model="m", provider="p")]
        )
        sent, send = _collect_sends()
        stopped = asyncio.Event()
        stopped.set()  # already stopped

        trace = await run_react_loop(_AGENT, _LLM_CONFIG, adapter, "hi", send, stopped)

        delta_msgs = [m for m in sent if m["type"] == "delta"]
        assert len(delta_msgs) == 0
        assert trace.error == "Stopped by user."


# ---------------------------------------------------------------------------
# ReAct loop — tool calls
# ---------------------------------------------------------------------------


class TestLoopWithTools:
    @pytest.mark.asyncio
    async def test_tool_call_then_respond(self) -> None:
        tc = ToolCall(id="tc1", name="calculator", arguments={"expression": "2+2"})
        adapter = _make_adapter(
            [
                LLMResponse(content=None, tool_calls=[tc], usage=_USAGE, model="m", provider="p"),  # type: ignore[arg-type]
                LLMResponse(
                    content="The answer is 4.", tool_calls=[], usage=_USAGE, model="m", provider="p"
                ),
            ]
        )
        sent, send = _collect_sends()
        stopped = asyncio.Event()

        with patch("app.agent.loop.run_tool", AsyncMock(return_value="4")):
            trace = await run_react_loop(
                _AGENT, _LLM_CONFIG, adapter, "What is 2+2?", send, stopped
            )

        tool_starts = [m for m in sent if m["type"] == "tool_start"]
        tool_ends = [m for m in sent if m["type"] == "tool_end"]
        assert len(tool_starts) == 1
        assert tool_starts[0]["tool_name"] == "calculator"
        assert len(tool_ends) == 1
        assert tool_ends[0]["result"] == "4"
        assert trace.final_response == "The answer is 4."
        assert len(trace.iterations) == 1

    @pytest.mark.asyncio
    async def test_llm_error_returns_error_trace(self) -> None:
        adapter = MagicMock()
        adapter.complete = AsyncMock(side_effect=RuntimeError("API down"))
        sent, send = _collect_sends()
        stopped = asyncio.Event()

        trace = await run_react_loop(_AGENT, _LLM_CONFIG, adapter, "hi", send, stopped)

        error_msgs = [m for m in sent if m["type"] == "error"]
        assert len(error_msgs) == 1
        assert trace.error is not None
        assert "API down" in trace.error

    @pytest.mark.asyncio
    async def test_no_tools_when_supports_tool_calls_false(self) -> None:
        llm_config = dict(_LLM_CONFIG, supports_tool_calls=False)
        adapter = _make_adapter(
            [LLMResponse(content="Sure!", tool_calls=[], usage=_USAGE, model="m", provider="p")]
        )
        _, send = _collect_sends()
        stopped = asyncio.Event()

        # Capture what tools arg was passed to complete()
        calls: list[Any] = []
        original_complete = adapter.complete

        async def capturing_complete(*args: Any, **kwargs: Any) -> Any:
            calls.append(kwargs.get("tools"))
            return await original_complete(*args, **kwargs)

        adapter.complete = capturing_complete

        await run_react_loop(_AGENT, llm_config, adapter, "hi", send, stopped)
        assert calls[0] is None  # tools should be None when not supported


# ---------------------------------------------------------------------------
# RunTrace.to_json
# ---------------------------------------------------------------------------


class TestRunTrace:
    def test_to_json_structure(self) -> None:
        trace = RunTrace(agent_id="agent-1", user_message="hello")
        trace.final_response = "hi"
        trace.usage = {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8}
        j = trace.to_json()
        assert j["agent_id"] == "agent-1"
        assert j["user_message"] == "hello"
        assert j["final_response"] == "hi"
        assert j["usage"]["total_tokens"] == 8
        assert j["error"] is None
