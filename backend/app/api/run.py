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
  { "type": "error",      "message": "..." }
"""

import asyncio
import json as _json
import uuid

import asyncpg
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.agent.loop import msg_done, msg_error, run_react_loop
from app.core.config import settings
from app.core.encryption import decrypt
from app.core.security import verify_token
from app.llm.adapter import build_adapter

router = APIRouter(prefix="/api/agents", tags=["run"])


async def _get_conn() -> asyncpg.Connection:
    return await asyncpg.connect(settings.database_url)  # type: ignore[union-attr]


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

    # ── Load agent + LLM config ──────────────────────────────────────────────
    try:
        conn = await _get_conn()
        try:
            agent_row = await conn.fetchrow(
                "SELECT * FROM agents WHERE id = $1 AND user_id = $2",
                agent_uid,
                uuid.UUID(user_id),
            )
            if agent_row is None:
                await websocket.send_json({"type": "error", "message": "Agent not found"})
                await websocket.close()
                return

            agent = dict(agent_row)
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
                    {
                        "type": "error",
                        "message": "No LLM configured for this agent. Go to the builder and select one.",
                    }
                )
                await websocket.close()
                return

            llm_row = await conn.fetchrow(
                "SELECT * FROM llm_configs WHERE id = $1 AND user_id = $2",
                agent["llm_config_id"],
                uuid.UUID(user_id),
            )
            if llm_row is None:
                await websocket.send_json({"type": "error", "message": "LLM config not found"})
                await websocket.close()
                return

            llm_config = dict(llm_row)
        finally:
            await conn.close()
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"Database error: {exc}"})
        await websocket.close()
        return

    # ── Decrypt credentials ──────────────────────────────────────────────────
    try:
        config_id = str(llm_config["id"])
        decrypted = decrypt(
            bytes(llm_config["config_enc"]),
            bytes(llm_config["config_iv"]),
            user_id,
            config_id,
        )
        decrypted["provider"] = llm_config["provider"]
        decrypted["model"] = str(llm_config["model"])
        decrypted["supports_tool_calls"] = bool(llm_config["supports_tool_calls"])
    except Exception as exc:
        await websocket.send_json({"type": "error", "message": f"Credential error: {exc}"})
        await websocket.close()
        return

    adapter = build_adapter(decrypted)
    stopped_event = asyncio.Event()

    async def send(msg: dict) -> None:  # type: ignore[type-arg]
        try:
            await websocket.send_json(msg)
        except Exception:
            stopped_event.set()

    # ── Main message loop ────────────────────────────────────────────────────
    try:
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

            user_message = (data.get("content") or "").strip()
            if not user_message:
                continue

            stopped_event.clear()

            trace = await run_react_loop(
                agent=agent,
                llm_config=decrypted,
                adapter=adapter,
                user_message=user_message,
                send=send,
                stopped_event=stopped_event,
            )

            # ── Persist trace ────────────────────────────────────────────────
            trace_id = str(uuid.uuid4())
            try:
                conn2 = await _get_conn()
                try:
                    await conn2.execute(
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
                finally:
                    await conn2.close()
            except Exception:
                pass  # Trace save failure must not fail the run

            if not trace.error:
                await send(msg_done(trace_id, trace.usage))

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        import contextlib

        with contextlib.suppress(Exception):
            await websocket.send_json(msg_error(str(exc)))
