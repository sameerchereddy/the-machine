"""
Default tools available to all agents.
Each tool is a pure async function returning a plain string result.
"""

import ast
import asyncio
import ipaddress
import math
import re
import socket
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote, urlparse

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
_TOOL_RESULT_LIMIT = 4000


async def _resolve_safe(hostname: str) -> tuple[str | None, str]:
    """
    Resolve *hostname* asynchronously and validate it is not private/reserved.

    Returns (resolved_ip, "") on success or (None, reason) on failure.
    DNS resolution failures and deliberate SSRF blocks return distinct reason
    strings to aid debugging.
    """
    loop = asyncio.get_running_loop()
    try:
        resolved = await loop.run_in_executor(None, socket.gethostbyname, hostname)
    except OSError:
        return None, "DNS resolution failed for hostname"
    try:
        addr = ipaddress.ip_address(resolved)
    except ValueError:
        return None, "DNS resolution failed for hostname"
    if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
        return None, "URL resolves to a private or reserved IP address"
    return resolved, ""


class _PinnedTransport(httpx.AsyncHTTPTransport):
    """
    Connect to *resolved_ip* (pre-validated) but use the original hostname for
    TLS SNI and certificate verification.  This prevents DNS rebinding: DNS is
    resolved once at validation time and the address is locked in for the actual
    HTTP connection so a second DNS lookup cannot redirect to a private IP.
    """

    def __init__(self, resolved_ip: str, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._resolved_ip = resolved_ip

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        original_host = request.url.host
        pinned_url = request.url.copy_with(host=self._resolved_ip)
        # sni_hostname tells httpcore to use the original hostname for TLS SNI
        # and certificate verification even though we connect to the IP.
        extensions = {**request.extensions, "sni_hostname": original_host.encode("ascii")}
        pinned = httpx.Request(
            request.method,
            pinned_url,
            headers=request.headers,
            stream=request.stream,
            extensions=extensions,
        )
        return await super().handle_async_request(pinned)


async def tool_url_reader(url: str) -> str:
    try:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return "Error: URL not allowed. Only public https:// URLs are supported."
    except Exception:
        return "Error: URL not allowed. Only public https:// URLs are supported."

    resolved_ip, reason = await _resolve_safe(parsed.hostname)
    if resolved_ip is None:
        return f"Error: URL not allowed — {reason}."

    try:
        transport = _PinnedTransport(resolved_ip)
        async with httpx.AsyncClient(transport=transport, follow_redirects=True, timeout=15) as client:
            resp = await client.get(url, headers=_HEADERS)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:_TOOL_RESULT_LIMIT]
    except Exception as exc:
        return f"Error fetching URL: {exc}"


# ---------------------------------------------------------------------------
# Wikipedia search
# ---------------------------------------------------------------------------


async def tool_wikipedia_search(query: str) -> str:
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            slug = quote(query.strip().replace(" ", "_"), safe="_")
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
                    return f"{title}: {extract}{suffix}"[:_TOOL_RESULT_LIMIT]

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
            slug2 = quote(title.replace(" ", "_"), safe="_")
            summary_resp = await client.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug2}",
                headers=_HEADERS,
            )
            if summary_resp.status_code == 200:
                data2 = summary_resp.json()
                extract2 = data2.get("extract", "No summary available.")
                url2 = data2.get("content_urls", {}).get("desktop", {}).get("page", "")
                suffix2 = f"\nSource: {url2}" if url2 else ""
                return f"{title}: {extract2}{suffix2}"[:_TOOL_RESULT_LIMIT]
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
            resp.raise_for_status()
            data = resp.json()

        parts: list[str] = []
        if data.get("AbstractText"):
            parts.append(data["AbstractText"])
            if data.get("AbstractURL"):
                parts.append(f"Source: {data['AbstractURL']}")

        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                parts.append(topic["Text"])

        result = "\n\n".join(parts) if parts else "No results found. Try a more specific query."
        return result[:_TOOL_RESULT_LIMIT]
    except Exception as exc:
        return f"Error: {exc}"


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_REQUIRED_ARGS: dict[str, list[str]] = {
    "calculator": ["expression"],
    "url_reader": ["url"],
    "wikipedia_search": ["query"],
    "web_search": ["query"],
}


async def run_tool(name: str, arguments: dict[str, Any]) -> str:
    """Route a tool call to the correct implementation."""
    required = _REQUIRED_ARGS.get(name, [])
    missing = [arg for arg in required if not arguments.get(arg)]
    if missing:
        return f"Error: missing required argument(s): {', '.join(missing)}"

    if name == "calculator":
        return await tool_calculator(arguments["expression"])
    elif name == "current_datetime":
        return await tool_current_datetime()
    elif name == "url_reader":
        return await tool_url_reader(arguments["url"])
    elif name == "wikipedia_search":
        return await tool_wikipedia_search(arguments["query"])
    elif name == "web_search":
        return await tool_web_search(arguments["query"])
    else:
        return f"Unknown tool: {name!r}"
