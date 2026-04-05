"""
LLM Config CRUD + ping endpoints.

All routes are protected — requires valid session cookie.
Credentials are AES-256-GCM encrypted before storage.
"""
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import CurrentUser
from app.core.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/llm-configs", tags=["llm-configs"])

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

PROVIDERS = {
    "openai",
    "anthropic",
    "gemini",
    "grok",
    "bedrock",
    "azure",
    "ollama",
    "custom",
}


class LLMConfigCreate(BaseModel):
    name: str
    provider: str
    model: str
    is_default: bool = False
    supports_tool_calls: bool = True
    context_window: int | None = None
    # Provider-specific credentials — stored encrypted
    config: dict[str, Any]


class LLMConfigUpdate(BaseModel):
    name: str | None = None
    model: str | None = None
    is_default: bool | None = None
    supports_tool_calls: bool | None = None
    context_window: int | None = None
    config: dict[str, Any] | None = None


class LLMConfigResponse(BaseModel):
    id: str
    name: str
    provider: str
    model: str
    is_default: bool
    supports_tool_calls: bool
    context_window: int | None
    # config is returned with api_key masked
    config: dict[str, Any]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _get_conn() -> asyncpg.Connection:
    if not settings or not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    return await asyncpg.connect(settings.database_url)


def _parse_uuid(value: str) -> uuid.UUID:
    """Parse a UUID string, raising 404 on invalid format."""
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found") from None


def _mask_config(config: dict[str, Any]) -> dict[str, Any]:
    """Replace sensitive key values with a masked string."""
    masked = dict(config)
    for key in ("api_key", "secret_access_key", "password"):
        if key in masked and masked[key]:
            raw = str(masked[key])
            masked[key] = raw[:4] + "••••" + raw[-4:] if len(raw) > 8 else "••••••••"
    return masked


def _row_to_response(row: asyncpg.Record, config: dict[str, Any]) -> LLMConfigResponse:
    return LLMConfigResponse(
        id=str(row["id"]),
        name=row["name"],
        provider=row["provider"],
        model=row["model"],
        is_default=row["is_default"],
        supports_tool_calls=row["supports_tool_calls"],
        context_window=row["context_window"],
        config=_mask_config(config),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("", response_model=list[LLMConfigResponse])
async def list_configs(current_user: CurrentUser) -> list[LLMConfigResponse]:
    user_id = current_user["id"]
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT * FROM llm_configs WHERE user_id = $1 ORDER BY created_at",
            uuid.UUID(user_id),
        )
        result = []
        for row in rows:
            config_id = str(row["id"])
            config = decrypt(bytes(row["config_enc"]), bytes(row["config_iv"]), user_id, config_id)
            result.append(_row_to_response(row, config))
        return result
    finally:
        await conn.close()


@router.post("", response_model=LLMConfigResponse, status_code=status.HTTP_201_CREATED)
async def create_config(body: LLMConfigCreate, current_user: CurrentUser) -> LLMConfigResponse:
    user_id = current_user["id"]
    if body.provider not in PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider '{body.provider}'. Must be one of: {sorted(PROVIDERS)}",
        )

    # Generate the ID client-side so we can bind AAD before the insert
    new_id = uuid.uuid4()
    config_enc, config_iv = encrypt(body.config, user_id, str(new_id))

    conn = await _get_conn()
    try:
        async with conn.transaction():
            if body.is_default:
                await conn.execute(
                    "UPDATE llm_configs SET is_default = false WHERE user_id = $1",
                    uuid.UUID(user_id),
                )
            row = await conn.fetchrow(
                """
                INSERT INTO llm_configs
                    (id, user_id, name, provider, model, is_default,
                     supports_tool_calls, context_window, config_enc, config_iv)
                VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
                RETURNING *
                """,
                new_id,
                uuid.UUID(user_id),
                body.name,
                body.provider,
                body.model,
                body.is_default,
                body.supports_tool_calls,
                body.context_window,
                config_enc,
                config_iv,
            )
        return _row_to_response(row, body.config)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.get("/{config_id}", response_model=LLMConfigResponse)
async def get_config(config_id: str, current_user: CurrentUser) -> LLMConfigResponse:
    user_id = current_user["id"]
    config_uid = _parse_uuid(config_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM llm_configs WHERE id = $1 AND user_id = $2",
            config_uid,
            uuid.UUID(user_id),
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
        config = decrypt(bytes(row["config_enc"]), bytes(row["config_iv"]), user_id, config_id)
        return _row_to_response(row, config)
    finally:
        await conn.close()


@router.patch("/{config_id}", response_model=LLMConfigResponse)
async def update_config(
    config_id: str, body: LLMConfigUpdate, current_user: CurrentUser
) -> LLMConfigResponse:
    user_id = current_user["id"]
    config_uid = _parse_uuid(config_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM llm_configs WHERE id = $1 AND user_id = $2",
            config_uid,
            uuid.UUID(user_id),
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")

        name = body.name if body.name is not None else row["name"]
        model = body.model if body.model is not None else row["model"]
        is_default = body.is_default if body.is_default is not None else row["is_default"]
        supports_tool_calls = (
            body.supports_tool_calls
            if body.supports_tool_calls is not None
            else row["supports_tool_calls"]
        )
        context_window = body.context_window if body.context_window is not None else row["context_window"]

        if body.config is not None:
            config_enc, config_iv = encrypt(body.config, user_id, config_id)
            new_config = body.config
        else:
            config_enc = bytes(row["config_enc"])
            config_iv = bytes(row["config_iv"])
            new_config = decrypt(config_enc, config_iv, user_id, config_id)

        async with conn.transaction():
            if is_default:
                await conn.execute(
                    "UPDATE llm_configs SET is_default = false WHERE user_id = $1 AND id != $2",
                    uuid.UUID(user_id),
                    config_uid,
                )
            updated = await conn.fetchrow(
                """
                UPDATE llm_configs SET
                    name = $1, model = $2, is_default = $3,
                    supports_tool_calls = $4, context_window = $5,
                    config_enc = $6, config_iv = $7,
                    updated_at = now()
                WHERE id = $8 AND user_id = $9
                RETURNING *
                """,
                name,
                model,
                is_default,
                supports_tool_calls,
                context_window,
                config_enc,
                config_iv,
                config_uid,
                uuid.UUID(user_id),
            )
        return _row_to_response(updated, new_config)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_config(config_id: str, current_user: CurrentUser) -> None:
    user_id = current_user["id"]
    config_uid = _parse_uuid(config_id)
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM llm_configs WHERE id = $1 AND user_id = $2",
            config_uid,
            uuid.UUID(user_id),
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Ping — test credentials by sending a minimal request to the provider
# ---------------------------------------------------------------------------

class PingRequest(BaseModel):
    provider: str
    model: str
    config: dict[str, Any]


@router.post("/ping")
async def ping_credentials(body: PingRequest, current_user: CurrentUser) -> dict[str, object]:
    """Test credentials directly — no DB read or write."""
    if body.provider not in PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unknown provider '{body.provider}'",
        )
    try:
        latency_ms = await _ping_provider(body.provider, body.model, body.config)
        return {"ok": True, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _sanitize_error(exc)}


@router.post("/{config_id}/ping")
async def ping_config(config_id: str, current_user: CurrentUser) -> dict[str, object]:
    """Test an already-saved config by ID."""
    user_id = current_user["id"]
    config_uid = _parse_uuid(config_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM llm_configs WHERE id = $1 AND user_id = $2",
            config_uid,
            uuid.UUID(user_id),
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Config not found")
        config = decrypt(bytes(row["config_enc"]), bytes(row["config_iv"]), user_id, config_id)
    finally:
        await conn.close()

    provider = row["provider"]
    model = str(row["model"])

    try:
        latency_ms = await _ping_provider(provider, model, config)
        return {"ok": True, "latency_ms": latency_ms}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _sanitize_error(exc)}


def _sanitize_error(exc: Exception) -> str:
    """
    Return a safe error message stripped of any credentials or request IDs.
    We surface the HTTP status code and provider error type when available,
    but never raw exception details that might include partial keys or URLs.
    """
    msg = str(exc)
    # Extract just the status code + message type if it looks like an API error
    for marker in ("Error code:", "status_code=", "HTTP Error"):
        if marker in msg:
            # Return up to the first newline — status line only
            return msg.split("\n")[0][:200]
    # Generic fallback — don't leak internal details
    return "Provider request failed. Check your credentials and model name."


async def _ping_provider(provider: str, model: str, config: dict[str, Any]) -> float:
    """Send a minimal 1-token request to verify credentials. Returns latency in ms."""
    import time

    start = time.monotonic()

    if provider == "anthropic":
        await _ping_anthropic(model, config)
    elif provider in ("openai", "azure", "grok", "custom"):
        await _ping_openai_compat(provider, model, config)
    elif provider == "gemini":
        await _ping_gemini(model, config)
    elif provider == "ollama":
        await _ping_ollama(model, config)
    elif provider == "bedrock":
        await _ping_bedrock(model, config)
    else:
        raise ValueError(f"Unsupported provider: {provider}")

    return round((time.monotonic() - start) * 1000, 1)


async def _ping_anthropic(model: str, config: dict[str, Any]) -> None:
    import anthropic

    client = anthropic.AsyncAnthropic(api_key=config["api_key"])
    await client.messages.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "hi"}],
    )


async def _ping_openai_compat(provider: str, model: str, config: dict[str, Any]) -> None:
    import openai

    base_url = config.get("base_url")
    if provider == "azure":
        client = openai.AsyncAzureOpenAI(
            api_key=config["api_key"],
            azure_endpoint=config["base_url"],
            api_version=config.get("api_version", "2024-02-01"),
        )
    else:
        client = openai.AsyncOpenAI(
            api_key=config["api_key"],
            base_url=base_url,
        )
    await client.chat.completions.create(
        model=model,
        max_tokens=1,
        messages=[{"role": "user", "content": "hi"}],
    )


async def _ping_gemini(model: str, config: dict[str, Any]) -> None:
    import google.generativeai as genai  # type: ignore[import-untyped]

    genai.configure(api_key=config["api_key"])
    gemini = genai.GenerativeModel(model)
    await gemini.generate_content_async("hi")


async def _ping_ollama(model: str, config: dict[str, Any]) -> None:
    import httpx

    base_url = config.get("base_url") or "http://127.0.0.1:11434"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "hi"}],
                "stream": False,
                "options": {"num_predict": 1},
            },
            timeout=15,
        )
        resp.raise_for_status()


async def _ping_bedrock(model: str, config: dict[str, Any]) -> None:
    import json as _json

    import aioboto3  # type: ignore[import-untyped]

    session = aioboto3.Session(
        aws_access_key_id=config["access_key_id"],
        aws_secret_access_key=config["secret_access_key"],
        region_name=config.get("region", "us-east-1"),
    )
    async with session.client("bedrock-runtime") as client:
        await client.invoke_model(
            modelId=model,
            body=_json.dumps(
                {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 1,
                 "messages": [{"role": "user", "content": "hi"}]}
            ),
            contentType="application/json",
            accept="application/json",
        )
