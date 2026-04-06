"""
Default tools available to all agents.
Each tool is a pure async function returning a plain string result.
"""

import ast
import math
import re
from datetime import UTC, datetime
from typing import Any

import httpx
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Tool schemas — OpenAI function-calling format
# ---------------------------------------------------------------------------

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": (
                "Evaluate a mathematical expression. Supports arithmetic (+, -, *, /, **), "
                "parentheses, and math functions: sqrt, sin, cos, tan, log, log10, exp, "
                "floor, ceil, pi, e."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": "The expression to evaluate, e.g. 'sqrt(144)' or '2**10'",
                    }
                },
                "required": ["expression"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "current_datetime",
            "description": "Returns the current UTC date and time. Use when the user asks about the current time or date.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "url_reader",
            "description": "Fetches and returns the readable text content of a public web page.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Full URL including https://, e.g. 'https://example.com/article'",
                    }
                },
                "required": ["url"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "wikipedia_search",
            "description": (
                "Search Wikipedia and return an article summary. "
                "Best for factual questions about people, places, events, and concepts."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The topic to look up"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": (
                "Search the web for recent or general information. "
                "Use for current events, news, prices, or anything not in Wikipedia."
            ),
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "The search query"}},
                "required": ["query"],
            },
        },
    },
]

# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

_SAFE_NAMES: dict[str, Any] = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_SAFE_NAMES.update({"abs": abs, "round": round, "min": min, "max": max})

_SAFE_NODES = (
    ast.Expression,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.Mod,
    ast.FloorDiv,
    ast.UAdd,
    ast.USub,
)


def _safe_eval(expression: str) -> str:
    tree = ast.parse(expression.strip(), mode="eval")
    for node in ast.walk(tree):
        if not isinstance(node, _SAFE_NODES):
            raise ValueError(f"Disallowed expression node: {type(node).__name__}")
        if isinstance(node, ast.Name) and node.id not in _SAFE_NAMES:
            raise ValueError(f"Unknown name: {node.id!r}")
    result = eval(compile(tree, "<expr>", "eval"), {"__builtins__": {}}, _SAFE_NAMES)
    return str(result)


async def tool_calculator(expression: str) -> str:
    try:
        return _safe_eval(expression)
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Current datetime
# ---------------------------------------------------------------------------


async def tool_current_datetime() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")


# ---------------------------------------------------------------------------
# URL reader
# ---------------------------------------------------------------------------

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; TheMachineBot/1.0)"}


async def tool_url_reader(url: str) -> str:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:4000]
    except Exception as exc:
        return f"Error fetching URL: {exc}"


# ---------------------------------------------------------------------------
# Wikipedia search
# ---------------------------------------------------------------------------


async def tool_wikipedia_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            slug = query.strip().replace(" ", "_")
            resp = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers=_HEADERS,
            )
            if resp.status_code == 200:
                data = resp.json()
                extract = data.get("extract", "")
                if extract:
                    title = data.get("title", query)
                    url = data.get("content_urls", {}).get("desktop", {}).get("page", "")
                    suffix = f"\nSource: {url}" if url else ""
                    return f"{title}: {extract}{suffix}"

            # Fall back to search API
            search_resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": query,
                    "format": "json",
                    "srlimit": 1,
                },
                headers=_HEADERS,
            )
            results = search_resp.json().get("query", {}).get("search", [])
            if not results:
                return "No Wikipedia article found."

            title = results[0]["title"]
            slug2 = title.replace(" ", "_")
            summary_resp = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug2}",
                headers=_HEADERS,
            )
            if summary_resp.status_code == 200:
                data2 = summary_resp.json()
                extract2 = data2.get("extract", "No summary available.")
                url2 = data2.get("content_urls", {}).get("desktop", {}).get("page", "")
                suffix2 = f"\nSource: {url2}" if url2 else ""
                return f"{title}: {extract2}{suffix2}"
            return f"Found article '{title}' but could not retrieve summary."
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Web search (DuckDuckGo Instant Answer API)
# ---------------------------------------------------------------------------


async def tool_web_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
                headers=_HEADERS,
            )
            data = resp.json()

        parts: list[str] = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
            if data.get("AbstractURL"):
                parts.append(f"Source: {data['AbstractURL']}")

        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])

        return "\n\n".join(parts) if parts else "No results found. Try a more specific query."
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------


async def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """Route a tool call to the correct implementation."""
    if name == "calculator":
        return await tool_calculator(arguments.get("expression", ""))
    elif name == "current_datetime":
        return await tool_current_datetime()
    elif name == "url_reader":
        return await tool_url_reader(arguments.get("url", ""))
    elif name == "wikipedia_search":
        return await tool_wikipedia_search(arguments.get("query", ""))
    elif name == "web_search":
        return await tool_web_search(arguments.get("query", ""))
    else:
        return f"Unknown tool: {name!r}"
