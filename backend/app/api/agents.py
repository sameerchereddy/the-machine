"""
Agent CRUD + tools API.

All routes are protected — requires valid session cookie.
Tool credentials (if any) are AES-256-GCM encrypted.
"""

import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import CurrentUser
from app.core.encryption import encrypt

router = APIRouter(prefix="/api/agents", tags=["agents"])

# ---------------------------------------------------------------------------
# Helpers (shared with llm_configs pattern)
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    if not settings or not settings.database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database not configured",
        )
    return await asyncpg.connect(settings.database_url)


def _parse_uuid(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from None


# ---------------------------------------------------------------------------
# Agent schemas
# ---------------------------------------------------------------------------


class AgentCreate(BaseModel):
    name: str = "Untitled Agent"
    llm_config_id: str | None = None


class AgentUpdate(BaseModel):
    name: str | None = None
    llm_config_id: str | None = None

    # Instructions block
    instructions: str | None = None
    persona_name: str | None = None
    response_style: str | None = None
    output_format: str | None = None
    output_schema: dict[str, Any] | None = None
    response_language: str | None = None
    show_reasoning: bool | None = None

    # Context block
    context_entries: list[dict[str, Any]] | None = None
    auto_inject_datetime: bool | None = None
    auto_inject_user_profile: bool | None = None
    context_render_as: str | None = None

    # Memory block
    history_window: int | None = None
    summarise_old_messages: bool | None = None
    long_term_enabled: bool | None = None
    memory_types: list[str] | None = None
    max_memories: int | None = None
    retention_days: int | None = None

    # Knowledge base block
    kb_top_k: int | None = None
    kb_similarity_threshold: float | None = None
    kb_reranking: bool | None = None
    kb_show_sources: bool | None = None
    kb_chunk_size: int | None = None
    kb_chunk_overlap: int | None = None

    # Guardrails block
    max_iterations: int | None = None
    on_max_iterations: str | None = None
    max_tool_calls_per_run: int | None = None
    max_tokens_per_run: int | None = None
    topic_restrictions: list[str] | None = None
    allow_clarifying_questions: bool | None = None
    pii_detection: bool | None = None
    safe_tool_mode: bool | None = None


class AgentResponse(BaseModel):
    id: str
    name: str
    llm_config_id: str | None

    instructions: str
    persona_name: str | None
    response_style: str
    output_format: str
    output_schema: dict[str, Any] | None
    response_language: str
    show_reasoning: bool

    context_entries: list[Any]
    auto_inject_datetime: bool
    auto_inject_user_profile: bool
    context_render_as: str

    history_window: int
    summarise_old_messages: bool
    long_term_enabled: bool
    memory_types: list[Any]
    max_memories: int
    retention_days: int

    kb_top_k: int
    kb_similarity_threshold: float
    kb_reranking: bool
    kb_show_sources: bool
    kb_chunk_size: int
    kb_chunk_overlap: int

    max_iterations: int
    on_max_iterations: str
    max_tool_calls_per_run: int
    max_tokens_per_run: int
    topic_restrictions: list[Any]
    allow_clarifying_questions: bool
    pii_detection: bool
    safe_tool_mode: bool


class AgentSummary(BaseModel):
    id: str
    name: str
    llm_config_id: str | None
    created_at: str
    updated_at: str


def _row_to_response(row: asyncpg.Record) -> AgentResponse:
    return AgentResponse(
        id=str(row["id"]),
        name=row["name"],
        llm_config_id=str(row["llm_config_id"]) if row["llm_config_id"] else None,
        instructions=row["instructions"],
        persona_name=row["persona_name"],
        response_style=row["response_style"],
        output_format=row["output_format"],
        output_schema=row["output_schema"],
        response_language=row["response_language"],
        show_reasoning=row["show_reasoning"],
        context_entries=list(row["context_entries"]) if row["context_entries"] else [],
        auto_inject_datetime=row["auto_inject_datetime"],
        auto_inject_user_profile=row["auto_inject_user_profile"],
        context_render_as=row["context_render_as"],
        history_window=row["history_window"],
        summarise_old_messages=row["summarise_old_messages"],
        long_term_enabled=row["long_term_enabled"],
        memory_types=list(row["memory_types"]) if row["memory_types"] else [],
        max_memories=row["max_memories"],
        retention_days=row["retention_days"],
        kb_top_k=row["kb_top_k"],
        kb_similarity_threshold=row["kb_similarity_threshold"],
        kb_reranking=row["kb_reranking"],
        kb_show_sources=row["kb_show_sources"],
        kb_chunk_size=row["kb_chunk_size"],
        kb_chunk_overlap=row["kb_chunk_overlap"],
        max_iterations=row["max_iterations"],
        on_max_iterations=row["on_max_iterations"],
        max_tool_calls_per_run=row["max_tool_calls_per_run"],
        max_tokens_per_run=row["max_tokens_per_run"],
        topic_restrictions=list(row["topic_restrictions"]) if row["topic_restrictions"] else [],
        allow_clarifying_questions=row["allow_clarifying_questions"],
        pii_detection=row["pii_detection"],
        safe_tool_mode=row["safe_tool_mode"],
    )


# ---------------------------------------------------------------------------
# Agent CRUD
# ---------------------------------------------------------------------------


async def _check_llm_config_owner(
    conn: asyncpg.Connection, llm_config_uid: uuid.UUID, user_id: str
) -> None:
    """Raise 404 if the LLM config doesn't exist or belongs to another user."""
    row = await conn.fetchrow(
        "SELECT id FROM llm_configs WHERE id = $1 AND user_id = $2",
        llm_config_uid,
        uuid.UUID(user_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="LLM config not found")


@router.post("", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(body: AgentCreate, current_user: CurrentUser) -> AgentResponse:
    user_id = current_user["id"]
    llm_config_uid = _parse_uuid(body.llm_config_id) if body.llm_config_id else None
    conn = await _get_conn()
    try:
        if llm_config_uid:
            await _check_llm_config_owner(conn, llm_config_uid, user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO agents (user_id, name, llm_config_id)
            VALUES ($1, $2, $3)
            RETURNING *
            """,
            uuid.UUID(user_id),
            body.name,
            llm_config_uid,
        )
        return _row_to_response(row)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.get("", response_model=list[AgentSummary])
async def list_agents(current_user: CurrentUser) -> list[AgentSummary]:
    user_id = current_user["id"]
    conn = await _get_conn()
    try:
        rows = await conn.fetch(
            "SELECT id, name, llm_config_id, created_at, updated_at FROM agents WHERE user_id = $1 ORDER BY updated_at DESC",
            uuid.UUID(user_id),
        )
        return [
            AgentSummary(
                id=str(r["id"]),
                name=r["name"],
                llm_config_id=str(r["llm_config_id"]) if r["llm_config_id"] else None,
                created_at=r["created_at"].isoformat(),
                updated_at=r["updated_at"].isoformat(),
            )
            for r in rows
        ]
    finally:
        await conn.close()


@router.get("/{agent_id}", response_model=AgentResponse)
async def get_agent(agent_id: str, current_user: CurrentUser) -> AgentResponse:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND user_id = $2",
            agent_uid,
            uuid.UUID(user_id),
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        return _row_to_response(row)
    finally:
        await conn.close()


@router.put("/{agent_id}", response_model=AgentResponse)
async def update_agent(
    agent_id: str, body: AgentUpdate, current_user: CurrentUser
) -> AgentResponse:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    conn = await _get_conn()
    try:
        # Fetch existing to merge
        existing = await conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND user_id = $2",
            agent_uid,
            uuid.UUID(user_id),
        )
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")

        def _v(field: str, new: Any) -> Any:
            return new if new is not None else existing[field]

        # Use model_fields_set to distinguish explicit null (clear) from absent (keep)
        if "llm_config_id" in body.model_fields_set:
            llm_config_uid = _parse_uuid(body.llm_config_id) if body.llm_config_id else None
            if llm_config_uid:
                await _check_llm_config_owner(conn, llm_config_uid, user_id)
        else:
            llm_config_uid = existing["llm_config_id"]

        row = await conn.fetchrow(
            """
            UPDATE agents SET
                name = $1, llm_config_id = $2,
                instructions = $3, persona_name = $4, response_style = $5,
                output_format = $6, output_schema = $7, response_language = $8, show_reasoning = $9,
                context_entries = $10, auto_inject_datetime = $11, auto_inject_user_profile = $12,
                context_render_as = $13,
                history_window = $14, summarise_old_messages = $15, long_term_enabled = $16,
                memory_types = $17, max_memories = $18, retention_days = $19,
                kb_top_k = $20, kb_similarity_threshold = $21, kb_reranking = $22,
                kb_show_sources = $23, kb_chunk_size = $24, kb_chunk_overlap = $25,
                max_iterations = $26, on_max_iterations = $27, max_tool_calls_per_run = $28,
                max_tokens_per_run = $29, topic_restrictions = $30,
                allow_clarifying_questions = $31, pii_detection = $32, safe_tool_mode = $33,
                updated_at = now()
            WHERE id = $34 AND user_id = $35
            RETURNING *
            """,
            _v("name", body.name),
            llm_config_uid,
            _v("instructions", body.instructions),
            _v("persona_name", body.persona_name),
            _v("response_style", body.response_style),
            _v("output_format", body.output_format),
            body.output_schema if body.output_schema is not None else existing["output_schema"],
            _v("response_language", body.response_language),
            _v("show_reasoning", body.show_reasoning),
            body.context_entries
            if body.context_entries is not None
            else existing["context_entries"],
            _v("auto_inject_datetime", body.auto_inject_datetime),
            _v("auto_inject_user_profile", body.auto_inject_user_profile),
            _v("context_render_as", body.context_render_as),
            _v("history_window", body.history_window),
            _v("summarise_old_messages", body.summarise_old_messages),
            _v("long_term_enabled", body.long_term_enabled),
            body.memory_types if body.memory_types is not None else existing["memory_types"],
            _v("max_memories", body.max_memories),
            _v("retention_days", body.retention_days),
            _v("kb_top_k", body.kb_top_k),
            _v("kb_similarity_threshold", body.kb_similarity_threshold),
            _v("kb_reranking", body.kb_reranking),
            _v("kb_show_sources", body.kb_show_sources),
            _v("kb_chunk_size", body.kb_chunk_size),
            _v("kb_chunk_overlap", body.kb_chunk_overlap),
            _v("max_iterations", body.max_iterations),
            _v("on_max_iterations", body.on_max_iterations),
            _v("max_tool_calls_per_run", body.max_tool_calls_per_run),
            _v("max_tokens_per_run", body.max_tokens_per_run),
            body.topic_restrictions
            if body.topic_restrictions is not None
            else existing["topic_restrictions"],
            _v("allow_clarifying_questions", body.allow_clarifying_questions),
            _v("pii_detection", body.pii_detection),
            _v("safe_tool_mode", body.safe_tool_mode),
            agent_uid,
            uuid.UUID(user_id),
        )
        return _row_to_response(row)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.delete("/{agent_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_agent(agent_id: str, current_user: CurrentUser) -> None:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM agents WHERE id = $1 AND user_id = $2",
            agent_uid,
            uuid.UUID(user_id),
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------


class ToolCreate(BaseModel):
    tool_key: str
    name: str
    description: str
    parameters: dict[str, Any] = {}
    enabled: bool = True
    timeout_seconds: int = 15
    max_calls_per_run: int = 5
    retry_on_failure: bool = True
    show_result_in_chat: bool = True
    result_truncation_chars: int = 2000
    credentials: dict[str, Any] | None = None
    endpoint_url: str | None = None
    sort_order: int = 0


class ToolUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    parameters: dict[str, Any] | None = None
    enabled: bool | None = None
    timeout_seconds: int | None = None
    max_calls_per_run: int | None = None
    retry_on_failure: bool | None = None
    show_result_in_chat: bool | None = None
    result_truncation_chars: int | None = None
    credentials: dict[str, Any] | None = None
    endpoint_url: str | None = None
    sort_order: int | None = None


class ToolResponse(BaseModel):
    id: str
    agent_id: str
    tool_key: str
    name: str
    description: str
    parameters: dict[str, Any]
    enabled: bool
    timeout_seconds: int
    max_calls_per_run: int
    retry_on_failure: bool
    show_result_in_chat: bool
    result_truncation_chars: int
    has_credentials: bool
    endpoint_url: str | None
    sort_order: int


def _tool_row_to_response(row: asyncpg.Record) -> ToolResponse:
    return ToolResponse(
        id=str(row["id"]),
        agent_id=str(row["agent_id"]),
        tool_key=row["tool_key"],
        name=row["name"],
        description=row["description"],
        parameters=dict(row["parameters"]) if row["parameters"] else {},
        enabled=row["enabled"],
        timeout_seconds=row["timeout_seconds"],
        max_calls_per_run=row["max_calls_per_run"],
        retry_on_failure=row["retry_on_failure"],
        show_result_in_chat=row["show_result_in_chat"],
        result_truncation_chars=row["result_truncation_chars"],
        has_credentials=row["credentials_enc"] is not None,
        endpoint_url=row["endpoint_url"],
        sort_order=row["sort_order"],
    )


# ---------------------------------------------------------------------------
# Tool CRUD
# ---------------------------------------------------------------------------


async def _assert_agent_owner(conn: asyncpg.Connection, agent_id: str, user_id: str) -> None:
    row = await conn.fetchrow(
        "SELECT id FROM agents WHERE id = $1 AND user_id = $2",
        _parse_uuid(agent_id),
        uuid.UUID(user_id),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")


@router.get("/{agent_id}/tools", response_model=list[ToolResponse])
async def list_tools(agent_id: str, current_user: CurrentUser) -> list[ToolResponse]:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    conn = await _get_conn()
    try:
        await _assert_agent_owner(conn, agent_id, user_id)
        rows = await conn.fetch(
            "SELECT * FROM agent_tools WHERE agent_id = $1 ORDER BY sort_order, created_at",
            agent_uid,
        )
        return [_tool_row_to_response(r) for r in rows]
    finally:
        await conn.close()


@router.post("/{agent_id}/tools", response_model=ToolResponse, status_code=status.HTTP_201_CREATED)
async def add_tool(agent_id: str, body: ToolCreate, current_user: CurrentUser) -> ToolResponse:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    tool_id = uuid.uuid4()

    creds_enc: bytes | None = None
    creds_iv: bytes | None = None
    if body.credentials:
        creds_enc, creds_iv = encrypt(body.credentials, user_id, str(tool_id))

    conn = await _get_conn()
    try:
        await _assert_agent_owner(conn, agent_id, user_id)
        row = await conn.fetchrow(
            """
            INSERT INTO agent_tools
                (id, agent_id, user_id, tool_key, name, description, parameters,
                 enabled, timeout_seconds, max_calls_per_run, retry_on_failure,
                 show_result_in_chat, result_truncation_chars,
                 credentials_enc, credentials_iv, endpoint_url, sort_order)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17)
            RETURNING *
            """,
            tool_id,
            agent_uid,
            uuid.UUID(user_id),
            body.tool_key,
            body.name,
            body.description,
            body.parameters,
            body.enabled,
            body.timeout_seconds,
            body.max_calls_per_run,
            body.retry_on_failure,
            body.show_result_in_chat,
            body.result_truncation_chars,
            creds_enc,
            creds_iv,
            body.endpoint_url,
            body.sort_order,
        )
        return _tool_row_to_response(row)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.put("/{agent_id}/tools/{tool_id}", response_model=ToolResponse)
async def update_tool(
    agent_id: str, tool_id: str, body: ToolUpdate, current_user: CurrentUser
) -> ToolResponse:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    tool_uid = _parse_uuid(tool_id)

    conn = await _get_conn()
    try:
        await _assert_agent_owner(conn, agent_id, user_id)
        existing = await conn.fetchrow(
            "SELECT * FROM agent_tools WHERE id = $1 AND agent_id = $2",
            tool_uid,
            agent_uid,
        )
        if existing is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")

        def _v(field: str, new: Any) -> Any:
            return new if new is not None else existing[field]

        creds_enc = existing["credentials_enc"]
        creds_iv = existing["credentials_iv"]
        if body.credentials is not None:
            creds_enc, creds_iv = encrypt(body.credentials, user_id, tool_id)

        row = await conn.fetchrow(
            """
            UPDATE agent_tools SET
                name = $1, description = $2, parameters = $3,
                enabled = $4, timeout_seconds = $5, max_calls_per_run = $6,
                retry_on_failure = $7, show_result_in_chat = $8,
                result_truncation_chars = $9, credentials_enc = $10, credentials_iv = $11,
                endpoint_url = $12, sort_order = $13, updated_at = now()
            WHERE id = $14 AND agent_id = $15
            RETURNING *
            """,
            _v("name", body.name),
            _v("description", body.description),
            body.parameters if body.parameters is not None else existing["parameters"],
            _v("enabled", body.enabled),
            _v("timeout_seconds", body.timeout_seconds),
            _v("max_calls_per_run", body.max_calls_per_run),
            _v("retry_on_failure", body.retry_on_failure),
            _v("show_result_in_chat", body.show_result_in_chat),
            _v("result_truncation_chars", body.result_truncation_chars),
            creds_enc,
            creds_iv,
            _v("endpoint_url", body.endpoint_url),
            _v("sort_order", body.sort_order),
            tool_uid,
            agent_uid,
        )
        return _tool_row_to_response(row)  # type: ignore[arg-type]
    finally:
        await conn.close()


@router.delete("/{agent_id}/tools/{tool_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_tool(agent_id: str, tool_id: str, current_user: CurrentUser) -> None:
    user_id = current_user["id"]
    agent_uid = _parse_uuid(agent_id)
    tool_uid = _parse_uuid(tool_id)

    conn = await _get_conn()
    try:
        await _assert_agent_owner(conn, agent_id, user_id)
        result = await conn.execute(
            "DELETE FROM agent_tools WHERE id = $1 AND agent_id = $2",
            tool_uid,
            agent_uid,
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tool not found")
    finally:
        await conn.close()
