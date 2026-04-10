"""
Traces API.

Routes:
  GET /api/traces              — list recent traces for current user
  GET /api/traces/{trace_id}   — full trace detail
"""

from __future__ import annotations

import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.core.config import settings
from app.core.deps import CurrentUser

router = APIRouter(prefix="/api/traces", tags=["traces"])


async def _get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)


def _parse_uuid(value: str, label: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid {label}"
        ) from None


# ---------------------------------------------------------------------------
# Response schemas
# ---------------------------------------------------------------------------


class TraceSummary(BaseModel):
    id: str
    agent_id: str | None
    agent_name: str | None
    user_message: str
    total_tokens: int
    has_error: bool
    created_at: str


class TraceDetail(BaseModel):
    id: str
    agent_id: str | None
    agent_name: str | None
    created_at: str
    trace_json: dict[str, Any]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("", response_model=list[TraceSummary])
async def list_traces(
    current_user: CurrentUser,
    agent_id: str | None = None,
    limit: int = 50,
) -> list[TraceSummary]:
    user_id: str = current_user["id"]
    limit = min(limit, 100)
    conn = await _get_conn()
    try:
        if agent_id:
            rows = await conn.fetch(
                """SELECT t.id, t.agent_id, a.name AS agent_name,
                          t.user_message, t.trace_json, t.created_at
                   FROM agent_traces t
                   LEFT JOIN agents a ON a.id = t.agent_id
                   WHERE t.user_id = $1 AND t.agent_id = $2
                   ORDER BY t.created_at DESC
                   LIMIT $3""",
                _parse_uuid(user_id, "user_id"),
                _parse_uuid(agent_id, "agent_id"),
                limit,
            )
        else:
            rows = await conn.fetch(
                """SELECT t.id, t.agent_id, a.name AS agent_name,
                          t.user_message, t.trace_json, t.created_at
                   FROM agent_traces t
                   LEFT JOIN agents a ON a.id = t.agent_id
                   WHERE t.user_id = $1
                   ORDER BY t.created_at DESC
                   LIMIT $2""",
                _parse_uuid(user_id, "user_id"),
                limit,
            )
    finally:
        await conn.close()

    result: list[TraceSummary] = []
    for r in rows:
        tj: dict[str, Any] = r["trace_json"] if isinstance(r["trace_json"], dict) else {}
        usage = tj.get("usage") or {}
        result.append(
            TraceSummary(
                id=str(r["id"]),
                agent_id=str(r["agent_id"]) if r["agent_id"] else None,
                agent_name=r["agent_name"],
                user_message=r["user_message"],
                total_tokens=int(usage.get("total_tokens", 0)),
                has_error=bool(tj.get("error")),
                created_at=str(r["created_at"]),
            )
        )
    return result


@router.get("/{trace_id}", response_model=TraceDetail)
async def get_trace(
    trace_id: str,
    current_user: CurrentUser,
) -> TraceDetail:
    user_id: str = current_user["id"]
    conn = await _get_conn()
    try:
        row = await conn.fetchrow(
            """SELECT t.id, t.agent_id, a.name AS agent_name,
                      t.trace_json, t.created_at
               FROM agent_traces t
               LEFT JOIN agents a ON a.id = t.agent_id
               WHERE t.id = $1 AND t.user_id = $2""",
            _parse_uuid(trace_id, "trace_id"),
            _parse_uuid(user_id, "user_id"),
        )
    finally:
        await conn.close()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Trace not found")

    tj = row["trace_json"] if isinstance(row["trace_json"], dict) else {}
    return TraceDetail(
        id=str(row["id"]),
        agent_id=str(row["agent_id"]) if row["agent_id"] else None,
        agent_name=row["agent_name"],
        created_at=str(row["created_at"]),
        trace_json=tj,
    )
