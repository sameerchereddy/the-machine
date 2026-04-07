"""
Knowledge Base + Memory API.

Routes:
  POST   /api/agents/{agent_id}/knowledge/upload          — upload a document
  GET    /api/agents/{agent_id}/knowledge                 — list sources
  DELETE /api/agents/{agent_id}/knowledge/{source_id}     — delete source
  PUT    /api/agents/{agent_id}/knowledge/embedding-key   — save embedding API key

  GET    /api/agents/{agent_id}/memories                  — list memories
  DELETE /api/agents/{agent_id}/memories/{memory_id}      — delete memory
"""

from __future__ import annotations

import os
import re
import uuid

import asyncpg
from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, status
from pydantic import BaseModel
from supabase import create_client

from app.agent.indexer import index_source
from app.core.config import settings
from app.core.deps import CurrentUser
from app.core.encryption import decrypt, encrypt

router = APIRouter(prefix="/api/agents", tags=["knowledge"])

_ALLOWED_TYPES: dict[str, str] = {
    "application/pdf": "pdf",
    "text/plain": "txt",
    "text/markdown": "md",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _get_conn() -> asyncpg.Connection:
    if not settings or not settings.database_url:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database not configured")
    return await asyncpg.connect(settings.database_url)


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label}")


async def _require_agent(conn: asyncpg.Connection, agent_id: str, user_id: str) -> asyncpg.Record:
    """Fetch agent row and assert ownership. Raises 404 if not found."""
    row = await conn.fetchrow(
        "SELECT * FROM agents WHERE id = $1 AND user_id = $2",
        _parse_uuid(agent_id, "agent_id"),
        _parse_uuid(user_id, "user_id"),
    )
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    return row


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class KnowledgeSourceResponse(BaseModel):
    id: str
    name: str
    source_type: str
    file_size_bytes: int | None
    chunk_count: int
    status: str
    error_message: str | None
    created_at: str


class MemoryResponse(BaseModel):
    id: str
    content: str
    memory_type: str
    created_at: str
    expires_at: str | None


class EmbeddingKeyBody(BaseModel):
    api_key: str


# ---------------------------------------------------------------------------
# Knowledge routes
# ---------------------------------------------------------------------------


@router.post("/{agent_id}/knowledge/upload", status_code=status.HTTP_201_CREATED)
async def upload_knowledge_source(
    agent_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
    current_user: CurrentUser,
) -> KnowledgeSourceResponse:
    user_id: str = current_user["id"]

    # File type check
    content_type = file.content_type or ""
    source_type = _ALLOWED_TYPES.get(content_type)
    if not source_type:
        # Fallback: check extension
        fn = (file.filename or "").lower()
        if fn.endswith(".pdf"):
            source_type = "pdf"
        elif fn.endswith(".docx"):
            source_type = "docx"
        elif fn.endswith(".md"):
            source_type = "md"
        elif fn.endswith(".txt"):
            source_type = "txt"
        else:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Unsupported file type. Allowed: PDF, TXT, MD, DOCX.",
            )

    # File size check
    max_bytes = (settings.max_kb_file_size_mb if settings else 20) * 1024 * 1024
    data = await file.read()
    if len(data) > max_bytes:
        max_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large. Maximum size is {max_mb} MB.",
        )

    # Sanitize filename: basename only, strip non-printable chars, cap length
    raw_name = os.path.basename(file.filename or f"document.{source_type}")
    safe_name = re.sub(r"[^\x20-\x7E]", "", raw_name)[:255] or f"document.{source_type}"

    conn = await _get_conn()
    try:
        agent_row = await _require_agent(conn, agent_id, user_id)

        # Resolve embedding key: OpenAI agents use their LLM key; others need a stored fallback key
        if not agent_row["llm_config_id"]:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Configure an LLM for this agent before uploading knowledge sources.",
            )
        llm_row = await conn.fetchrow(
            "SELECT * FROM llm_configs WHERE id=$1 AND user_id=$2",
            agent_row["llm_config_id"],
            uuid.UUID(user_id),
        )
        if llm_row is None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="LLM config not found.")

        provider = str(llm_row["provider"])
        if provider == "openai":
            try:
                llm_data = decrypt(
                    bytes(llm_row["config_enc"]),
                    bytes(llm_row["config_iv"]),
                    user_id,
                    str(llm_row["id"]),
                )
                embedding_api_key = str(llm_data["api_key"])
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to decrypt LLM credentials.",
                )
        elif agent_row["embedding_api_key_enc"]:
            try:
                emb_data = decrypt(
                    bytes(agent_row["embedding_api_key_enc"]),
                    bytes(agent_row["embedding_api_key_iv"]),
                    user_id,
                    str(agent_row["id"]),
                )
                embedding_api_key = str(emb_data["api_key"])
            except Exception:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Failed to decrypt embedding API key.",
                )
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Knowledge Base requires OpenAI embeddings (text-embedding-3-small). "
                    "Add an OpenAI API key in the Knowledge Base block."
                ),
            )

        # Upload to Supabase Storage
        storage_path = f"{user_id}/{agent_id}/{uuid.uuid4()}.{source_type}"
        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        sb.storage.from_(settings.storage_bucket).upload(
            path=storage_path,
            file=data,
            file_options={"content-type": content_type or "application/octet-stream"},
        )

        # Insert knowledge_sources row
        source_id = str(uuid.uuid4())
        row = await conn.fetchrow(
            """INSERT INTO knowledge_sources
                   (id, agent_id, user_id, name, source_type, storage_path, file_size_bytes, status)
               VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending')
               RETURNING *""",
            uuid.UUID(source_id),
            uuid.UUID(agent_id),
            uuid.UUID(user_id),
            safe_name,
            source_type,
            storage_path,
            len(data),
        )
    finally:
        await conn.close()

    # Kick off indexing in the background
    background_tasks.add_task(
        index_source,
        source_id=source_id,
        agent_id=agent_id,
        user_id=user_id,
        storage_path=storage_path,
        source_name=safe_name,
        source_type=source_type,
        embedding_api_key=embedding_api_key,
        chunk_size=int(agent_row["kb_chunk_size"]),
        chunk_overlap=int(agent_row["kb_chunk_overlap"]),
    )

    return KnowledgeSourceResponse(
        id=str(row["id"]),
        name=row["name"],
        source_type=row["source_type"],
        file_size_bytes=row["file_size_bytes"],
        chunk_count=row["chunk_count"],
        status=row["status"],
        error_message=row["error_message"],
        created_at=str(row["created_at"]),
    )


@router.get("/{agent_id}/knowledge")
async def list_knowledge_sources(
    agent_id: str,
    current_user: CurrentUser,
) -> list[KnowledgeSourceResponse]:
    user_id: str = current_user["id"]
    conn = await _get_conn()
    try:
        await _require_agent(conn, agent_id, user_id)
        rows = await conn.fetch(
            "SELECT * FROM knowledge_sources WHERE agent_id=$1 AND user_id=$2 ORDER BY created_at DESC",
            uuid.UUID(agent_id),
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()

    return [
        KnowledgeSourceResponse(
            id=str(r["id"]),
            name=r["name"],
            source_type=r["source_type"],
            file_size_bytes=r["file_size_bytes"],
            chunk_count=r["chunk_count"],
            status=r["status"],
            error_message=r["error_message"],
            created_at=str(r["created_at"]),
        )
        for r in rows
    ]


@router.delete("/{agent_id}/knowledge/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_knowledge_source(
    agent_id: str,
    source_id: str,
    current_user: CurrentUser,
) -> None:
    user_id: str = current_user["id"]
    conn = await _get_conn()
    try:
        await _require_agent(conn, agent_id, user_id)
        row = await conn.fetchrow(
            "SELECT storage_path FROM knowledge_sources WHERE id=$1 AND agent_id=$2 AND user_id=$3",
            _parse_uuid(source_id, "source_id"),
            _parse_uuid(agent_id, "agent_id"),
            _parse_uuid(user_id, "user_id"),
        )
        if row is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source not found")

        storage_path: str = row["storage_path"]
        # Delete DB row first (cascades to knowledge_chunks)
        await conn.execute("DELETE FROM knowledge_sources WHERE id=$1", _parse_uuid(source_id, "source_id"))
    finally:
        await conn.close()

    # Delete from Supabase Storage (best-effort — don't fail if already gone)
    try:
        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        sb.storage.from_(settings.storage_bucket).remove([storage_path])
    except Exception:
        pass


@router.put("/{agent_id}/knowledge/embedding-key", status_code=status.HTTP_204_NO_CONTENT)
async def save_embedding_key(
    agent_id: str,
    body: EmbeddingKeyBody,
    current_user: CurrentUser,
) -> None:
    user_id: str = current_user["id"]
    key = body.api_key.strip()
    if not key:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="api_key must not be empty")
    if not key.startswith("sk-"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="api_key does not look like a valid OpenAI key (must start with 'sk-')",
        )

    enc, iv = encrypt({"api_key": key}, user_id, agent_id)
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "UPDATE agents SET embedding_api_key_enc=$1, embedding_api_key_iv=$2 WHERE id=$3 AND user_id=$4",
            enc,
            iv,
            _parse_uuid(agent_id, "agent_id"),
            _parse_uuid(user_id, "user_id"),
        )
        if result == "UPDATE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
    finally:
        await conn.close()


# ---------------------------------------------------------------------------
# Memory routes
# ---------------------------------------------------------------------------


@router.get("/{agent_id}/memories")
async def list_memories(
    agent_id: str,
    current_user: CurrentUser,
) -> list[MemoryResponse]:
    user_id: str = current_user["id"]
    conn = await _get_conn()
    try:
        await _require_agent(conn, agent_id, user_id)
        rows = await conn.fetch(
            """SELECT id, content, memory_type, created_at, expires_at
               FROM agent_memories
               WHERE agent_id=$1 AND user_id=$2
                 AND (expires_at IS NULL OR expires_at > now())
               ORDER BY created_at DESC""",
            uuid.UUID(agent_id),
            uuid.UUID(user_id),
        )
    finally:
        await conn.close()

    return [
        MemoryResponse(
            id=str(r["id"]),
            content=r["content"],
            memory_type=r["memory_type"],
            created_at=str(r["created_at"]),
            expires_at=str(r["expires_at"]) if r["expires_at"] else None,
        )
        for r in rows
    ]


@router.delete("/{agent_id}/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    agent_id: str,
    memory_id: str,
    current_user: CurrentUser,
) -> None:
    user_id: str = current_user["id"]
    conn = await _get_conn()
    try:
        result = await conn.execute(
            "DELETE FROM agent_memories WHERE id=$1 AND agent_id=$2 AND user_id=$3",
            _parse_uuid(memory_id, "memory_id"),
            _parse_uuid(agent_id, "agent_id"),
            _parse_uuid(user_id, "user_id"),
        )
        if result == "DELETE 0":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
    finally:
        await conn.close()
