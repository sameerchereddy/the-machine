"""
Async knowledge-base indexing pipeline.
Called via FastAPI BackgroundTasks after a file is uploaded.

Pipeline:
  1. Mark source status → 'indexing'
  2. Download raw bytes from Supabase Storage
  3. Extract text  (PDF / DOCX / TXT / MD)
  4. Chunk text    (sliding-window, sentence-aware)
  5. Embed chunks  (text-embedding-3-small, batched)
  6. Insert into   knowledge_chunks (pgvector)
  7. Mark source status → 'ready'  (or 'error' on any failure)
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from typing import Any

import asyncpg
import pgvector.asyncpg
from openai import AsyncOpenAI
from supabase import create_client

from app.core.config import settings

logger = logging.getLogger(__name__)

_EMBED_MODEL = "text-embedding-3-small"
_EMBED_BATCH_SIZE = 100  # chunks per OpenAI embeddings request


# ---------------------------------------------------------------------------
# Text extraction
# ---------------------------------------------------------------------------


def _extract_text_pdf(data: bytes) -> str:
    import pypdf  # lazy import — optional dep only needed here

    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_text_docx(data: bytes) -> str:
    import docx  # python-docx

    doc = docx.Document(io.BytesIO(data))
    return "\n".join(para.text for para in doc.paragraphs)


def _extract_text_plain(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def extract_text(data: bytes, source_type: str) -> str:
    """Dispatch to the correct extractor based on source_type."""
    if source_type == "pdf":
        return _extract_text_pdf(data)
    elif source_type == "docx":
        return _extract_text_docx(data)
    else:  # txt, md
        return _extract_text_plain(data)


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

# Approximate: 1 token ≈ 4 characters
_CHARS_PER_TOKEN = 4


def chunk_text(text: str, chunk_size: int = 512, chunk_overlap: int = 64) -> list[str]:
    """
    Sliding-window chunker.
    chunk_size and chunk_overlap are in approximate tokens (chars / 4).
    Splits on sentence boundaries first to avoid cutting mid-sentence.
    Returns a list of non-empty chunk strings.
    """
    if not text.strip():
        return []

    chunk_chars = chunk_size * _CHARS_PER_TOKEN
    overlap_chars = chunk_overlap * _CHARS_PER_TOKEN

    # Split into sentences on common terminators
    import re as _re
    sentences = _re.split(r"(?<=[.!?\n])\s+", text.strip())

    chunks: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 > chunk_chars and current:
            chunks.append(current.strip())
            # Keep the overlap tail as the start of the next chunk
            tail = current[-min(overlap_chars, len(current)):] if overlap_chars else ""
            current = (tail + " " + sentence).lstrip() if tail else sentence
        else:
            current = (current + " " + sentence).lstrip()

    if current.strip():
        chunks.append(current.strip())

    return [c for c in chunks if c]


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------


async def index_source(
    source_id: str,
    agent_id: str,
    user_id: str,
    storage_path: str,
    source_name: str,
    source_type: str,
    embedding_api_key: str,
    chunk_size: int,
    chunk_overlap: int,
) -> None:
    """
    Full indexing pipeline for one knowledge source.
    All errors are caught and written back to knowledge_sources.status.
    """
    conn: asyncpg.Connection | None = None
    try:
        conn = await asyncpg.connect(settings.database_url)
        await conn.execute(
            "UPDATE knowledge_sources SET status='indexing', updated_at=now() WHERE id=$1",
            uuid.UUID(source_id),
        )
        logger.info("[source=%s] indexing started: %s", source_id, source_name)

        # ── Download from Supabase Storage ──────────────────────────────────
        sb = create_client(settings.supabase_url, settings.supabase_service_key)
        raw: bytes = await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: sb.storage.from_(settings.storage_bucket).download(storage_path),
        )
        logger.info("[source=%s] downloaded %d bytes", source_id, len(raw))

        # ── Extract text (CPU-bound — run in thread pool) ───────────────────
        text: str = await asyncio.get_running_loop().run_in_executor(
            None, extract_text, raw, source_type
        )
        if not text.strip():
            raise ValueError("No text could be extracted from the uploaded file.")

        # ── Chunk ────────────────────────────────────────────────────────────
        chunks = chunk_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
        if not chunks:
            raise ValueError("Document produced no chunks after extraction.")

        # ── Embed (batched, with retry on rate-limit) ────────────────────────
        oai = AsyncOpenAI(api_key=embedding_api_key)
        all_embeddings: list[list[float]] = []
        for i in range(0, len(chunks), _EMBED_BATCH_SIZE):
            batch = chunks[i : i + _EMBED_BATCH_SIZE]
            for attempt in range(3):
                try:
                    resp = await oai.embeddings.create(model=_EMBED_MODEL, input=batch)
                    break
                except Exception as exc:
                    if attempt == 2:
                        raise
                    # Exponential backoff for rate-limit / transient errors
                    wait = 2 ** attempt
                    logger.warning(
                        "Embedding attempt %d failed for source %s (%s); retrying in %ds",
                        attempt + 1, source_id, exc, wait,
                    )
                    await asyncio.sleep(wait)
            batch_embeddings = [e.embedding for e in resp.data]
            if len(batch_embeddings) != len(batch):
                raise ValueError(
                    f"Embedding count mismatch: got {len(batch_embeddings)}, expected {len(batch)}"
                )
            all_embeddings.extend(batch_embeddings)

        # ── Insert vectors ───────────────────────────────────────────────────
        await pgvector.asyncpg.register_vector(conn)
        rows: list[tuple[Any, ...]] = [
            (
                uuid.uuid4(),
                uuid.UUID(source_id),
                uuid.UUID(agent_id),
                uuid.UUID(user_id),
                chunks[idx],
                all_embeddings[idx],
                idx,
                {"source_name": source_name},
            )
            for idx in range(len(chunks))
        ]
        await conn.executemany(
            """INSERT INTO knowledge_chunks
                   (id, source_id, agent_id, user_id, content, embedding, chunk_index, metadata)
               VALUES ($1, $2, $3, $4, $5, $6, $7, $8)""",
            rows,
        )

        await conn.execute(
            "UPDATE knowledge_sources SET status='ready', chunk_count=$1, updated_at=now() WHERE id=$2",
            len(chunks),
            uuid.UUID(source_id),
        )
        logger.info("[source=%s] indexed %d chunks", source_id, len(chunks))

    except Exception as exc:
        logger.exception("Indexing failed for source %s", source_id)
        # Sanitise: only expose the exception type + a generic phrase, never raw messages
        # which may contain API keys, connection strings, or internal paths.
        safe_msg = f"{type(exc).__name__}: indexing failed"
        if isinstance(exc, ValueError):
            # ValueError messages are always our own, safe to surface
            safe_msg = str(exc)[:500]
        if conn:
            try:
                await conn.execute(
                    "UPDATE knowledge_sources SET status='error', error_message=$1, updated_at=now() WHERE id=$2",
                    safe_msg,
                    uuid.UUID(source_id),
                )
            except Exception:
                pass
    finally:
        if conn and not conn.is_closed():
            await conn.close()
