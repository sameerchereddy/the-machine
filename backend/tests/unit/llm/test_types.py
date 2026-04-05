"""
Tests for LLM shared types — mostly sanity checks on defaults.
"""

from app.llm.types import LLMResponse, StreamChunk, ToolCall, Usage


def test_usage_total() -> None:
    u = Usage(prompt_tokens=10, completion_tokens=5, total_tokens=15)
    assert u.total_tokens == 15


def test_llm_response_defaults() -> None:
    r = LLMResponse(
        content="hi",
        tool_calls=[],
        usage=Usage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="gpt-4o",
        provider="openai",
    )
    assert r.tool_calls == []


def test_stream_chunk_defaults() -> None:
    chunk = StreamChunk()
    assert chunk.delta == ""
    assert chunk.tool_calls == []
    assert chunk.finish_reason is None
    assert chunk.usage is None


def test_tool_call_fields() -> None:
    tc = ToolCall(id="call_abc", name="calculator", arguments={"expr": "2+2"})
    assert tc.name == "calculator"
    assert tc.arguments["expr"] == "2+2"
