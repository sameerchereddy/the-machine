"""
WebSocket endpoint for running agents.
WS /api/agents/{agent_id}/run

Client → Server (JSON):
  { "type": "message", "content": "<user text>" }
  { "type": "stop" }

Server → Client (JSON):
  { "type": "iteration", "n": 1 }
  { "type": "tool_start", "tool_id": "...", "tool_name": "...", "input": {...} }
  { "type": "tool_end",   "tool_id": "...", "result": "..." }
  { "type": "delta",      "content": "..." }
  { "type": "done",       "trace_id": "...", "usage": {...} }
  { "type": "stopped" }
  { "type": "error",      "message": "..." }
"""

import asyncio
import contextlib
import json as _json
import logging
import uuid
from typing import Any

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.loop import msg_done, msg_error, msg_stopped, run_react_loop
from app.core.config import settings
from app.core.encryption import decrypt
from app.core.security import verify_token
from app.llm.adapter import build_adapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agents", tags=["run"])

_MAX_USER_MESSAGE = 10_000  # characters; prevents memory/token DoS


async def _get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)


@router.websocket("/{agent_id}/run")
async def run_agent_ws(websocket: WebSocket, agent_id: str) -> None:
    await websocket.accept()

    # ── Auth via httpOnly cookie ─────────────────────────────────────────────
    token = websocket.cookies.get("access_token")
    if not token:
        await websocket.send_json({"type": "error", "message": "Not authenticated"})
        await websocket.close(code=4401)
        return

    try:
        current_user = verify_token(token)
    except Exception:
        await websocket.send_json({"type": "error", "message": "Invalid or expired token"})
        await websocket.close(code=4401)
        return

    user_id: str = current_user["id"]

    # ── Validate agent ID ────────────────────────────────────────────────────
    try:
        agent_uid = uuid.UUID(agent_id)
    except ValueError:
        await websocket.send_json({"type": "error", "message": "Invalid agent ID"})
        await websocket.close()
        return

    # ── Load agent + LLM config, run session, then close connection ──────────
    # All early-return paths go through this finally block so db_conn is always closed.
    db_conn: asyncpg.Connection | None = None
    try:
        db_conn = await _get_conn()
        agent_row = await db_conn.fetchrow(
            "SELECT * FROM agents WHERE id = $1 AND user_id = $2",
            agent_uid,
            uuid.UUID(user_id),
        )
        if agent_row is None:
            await websocket.send_json({"type": "error", "message": "Agent not found"})
            await websocket.close()
            return

        agent: dict[str, Any] = dict(agent_row)
        # asyncpg returns JSONB columns as raw strings — parse them
        for _f in ("context_entries", "memory_types", "topic_restrictions"):
            v = agent.get(_f)
            if isinstance(v, str):
                try:
                    agent[_f] = _json.loads(v)
                except Exception:
                    agent[_f] = []

        if not agent.get("llm_config_id"):
            await websocket.send_json(
                {"type": "error", "message": "No LLM configured for this agent. Go to the builder and select one."}
            )
            await websocket.close()
            return

        llm_row = await db_conn.fetchrow(
            "SELECT * FROM llm_configs WHERE id = $1 AND user_id = $2",
            agent["llm_config_id"],
            uuid.UUID(user_id),
        )
        if llm_row is None:
            await websocket.send_json({"type": "error", "message": "LLM config not found"})
            await websocket.close()
            return

        llm_config: dict[str, Any] = dict(llm_row)

        # ── Decrypt credentials ──────────────────────────────────────────────
        config_id = str(llm_config["id"])
        try:
            decrypted: dict[str, Any] = decrypt(
                bytes(llm_config["config_enc"]),
                bytes(llm_config["config_iv"]),
                user_id,
                config_id,
            )
        except Exception:
            logger.exception("Credential decrypt error during WS session setup")
            await websocket.send_json({"type": "error", "message": "Failed to decrypt LLM credentials."})
            await websocket.close()
            return

        decrypted["provider"] = llm_config["provider"]
        decrypted["model"] = str(llm_config["model"])
        decrypted["supports_tool_calls"] = bool(llm_config["supports_tool_calls"])

        adapter = build_adapter(decrypted)
        stopped_event = asyncio.Event()
        is_running = False

        async def send(msg: dict[str, Any]) -> None:
            try:
                await websocket.send_json(msg)
            except Exception:
                stopped_event.set()

        # ── Main message loop ────────────────────────────────────────────────
        while True:
            try:
                data = await websocket.receive_json()
            except WebSocketDisconnect:
                break

            if data.get("type") == "stop":
                stopped_event.set()
                continue

            if data.get("type") != "message":
                continue

            if is_running:
                # Reject new messages while a run is active; client should wait for done/stopped.
                continue

            user_message = (data.get("content") or "").strip()
            if not user_message:
                continue

            if len(user_message) > _MAX_USER_MESSAGE:
                await send({"type": "error", "message": f"Message too long (max {_MAX_USER_MESSAGE} characters)."})
                continue

            stopped_event.clear()
            is_running = True
            try:
                trace = await run_react_loop(
                    agent=agent,
                    llm_config=decrypted,
                    adapter=adapter,
                    user_message=user_message,
                    send=send,
                    stopped_event=stopped_event,
                )
            finally:
                is_running = False

            # ── Persist trace (reuse session connection) ─────────────────────
            trace_id = str(uuid.uuid4())
            try:
                if db_conn and not db_conn.is_closed():
                    await db_conn.execute(
                        """
                        INSERT INTO agent_traces
                            (id, agent_id, user_id, llm_config_id, user_message, trace_json)
                        VALUES ($1, $2, $3, $4, $5, $6::jsonb)
                        """,
                        uuid.UUID(trace_id),
                        agent_uid,
                        uuid.UUID(user_id),
                        agent["llm_config_id"],
                        user_message,
                        _json.dumps(trace.to_json()),
                    )
            except Exception:
                logger.exception("Failed to persist trace %s", trace_id)
                # Trace save failure must not fail the run

            if trace.error == "Stopped by user.":
                await send(msg_stopped())
            elif not trace.error:
                await send(msg_done(trace_id, trace.usage))

    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Unhandled error in WS run loop")
        with contextlib.suppress(Exception):
            await websocket.send_json(msg_error("An unexpected error occurred."))
    finally:
        if db_conn and not db_conn.is_closed():
            await db_conn.close()
