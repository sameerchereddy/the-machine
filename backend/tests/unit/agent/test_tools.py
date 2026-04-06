"""
Unit tests for default agent tools.
Network calls are mocked — no real HTTP requests.
"""

import pytest

from app.agent.tools import _safe_eval, run_tool, tool_calculator, tool_current_datetime

# ---------------------------------------------------------------------------
# Calculator — safe_eval
# ---------------------------------------------------------------------------


class TestSafeEval:
    def test_basic_arithmetic(self) -> None:
        assert _safe_eval("2 + 2") == "4"
        assert _safe_eval("10 - 3") == "7"
        assert _safe_eval("6 * 7") == "42"
        assert _safe_eval("10 / 4") == "2.5"

    def test_exponentiation(self) -> None:
        assert _safe_eval("2 ** 10") == "1024"

    def test_math_functions(self) -> None:
        result = _safe_eval("sqrt(144)")
        assert result == "12.0"

    def test_nested_expression(self) -> None:
        result = _safe_eval("(2 + 3) * (4 - 1)")
        assert result == "15"

    def test_constants(self) -> None:
        result = float(_safe_eval("pi"))
        assert abs(result - 3.14159) < 0.001

    def test_disallows_import(self) -> None:
        with pytest.raises((ValueError, SyntaxError)):
            _safe_eval("__import__('os')")

    def test_disallows_unknown_name(self) -> None:
        with pytest.raises(ValueError, match="Unknown name"):
            _safe_eval("foobar + 1")

    def test_disallows_list_comprehension(self) -> None:
        with pytest.raises((ValueError, SyntaxError)):
            _safe_eval("[x for x in range(10)]")


class TestToolCalculator:
    @pytest.mark.asyncio
    async def test_valid_expression(self) -> None:
        result = await tool_calculator("3 * 3")
        assert result == "9"

    @pytest.mark.asyncio
    async def test_error_returns_message(self) -> None:
        result = await tool_calculator("1 / 0")
        assert "Error" in result or "division by zero" in result.lower()

    @pytest.mark.asyncio
    async def test_invalid_expression(self) -> None:
        result = await tool_calculator("not valid math!!!")
        assert "Error" in result


# ---------------------------------------------------------------------------
# current_datetime
# ---------------------------------------------------------------------------


class TestCurrentDatetime:
    @pytest.mark.asyncio
    async def test_returns_utc_string(self) -> None:
        result = await tool_current_datetime()
        assert "UTC" in result
        # Should look like "2026-04-05 00:00:00 UTC"
        assert len(result) > 10


# ---------------------------------------------------------------------------
# run_tool dispatcher
# ---------------------------------------------------------------------------


class TestRunTool:
    @pytest.mark.asyncio
    async def test_calculator_dispatch(self) -> None:
        result = await run_tool("calculator", {"expression": "5 + 5"})
        assert result == "10"

    @pytest.mark.asyncio
    async def test_current_datetime_dispatch(self) -> None:
        result = await run_tool("current_datetime", {})
        assert "UTC" in result

    @pytest.mark.asyncio
    async def test_unknown_tool_returns_error(self) -> None:
        result = await run_tool("nonexistent_tool", {})
        assert "Unknown tool" in result
