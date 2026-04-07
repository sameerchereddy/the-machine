"""
Unit tests for the knowledge-base indexing pipeline.
Storage, OpenAI, and asyncpg are all mocked.
"""

from __future__ import annotations

import io
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agent.indexer import chunk_text, extract_text


# ---------------------------------------------------------------------------
# extract_text
# ---------------------------------------------------------------------------


class TestExtractText:
    def test_plain_text(self) -> None:
        data = b"Hello world"
        assert extract_text(data, "txt") == "Hello world"

    def test_markdown(self) -> None:
        data = b"# Title\n\nContent."
        assert extract_text(data, "md") == "# Title\n\nContent."

    def test_invalid_utf8_replaced(self) -> None:
        data = b"Hello \xff world"
        result = extract_text(data, "txt")
        assert "Hello" in result

    def test_pdf_extraction(self) -> None:
        mock_page = MagicMock()
        mock_page.extract_text.return_value = "Page one text."
        mock_reader = MagicMock()
        mock_reader.pages = [mock_page]

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = extract_text(b"fake-pdf-bytes", "pdf")

        assert result == "Page one text."

    def test_pdf_multi_page(self) -> None:
        pages = [MagicMock(extract_text=MagicMock(return_value=f"Page {i}.")) for i in range(3)]
        mock_reader = MagicMock(pages=pages)

        with patch("pypdf.PdfReader", return_value=mock_reader):
            result = extract_text(b"bytes", "pdf")

        assert "Page 0." in result
        assert "Page 2." in result

    def test_docx_extraction(self) -> None:
        para1 = MagicMock(text="First paragraph.")
        para2 = MagicMock(text="Second paragraph.")
        mock_doc = MagicMock(paragraphs=[para1, para2])

        with patch("docx.Document", return_value=mock_doc):
            result = extract_text(b"fake-docx", "docx")

        assert "First paragraph." in result
        assert "Second paragraph." in result


# ---------------------------------------------------------------------------
# chunk_text
# ---------------------------------------------------------------------------


class TestChunkText:
    def test_empty_returns_empty(self) -> None:
        assert chunk_text("", 512, 64) == []

    def test_whitespace_only_returns_empty(self) -> None:
        assert chunk_text("   \n  ", 512, 64) == []

    def test_short_text_is_single_chunk(self) -> None:
        text = "Hello world."
        chunks = chunk_text(text, chunk_size=512, chunk_overlap=64)
        assert len(chunks) == 1
        assert "Hello world." in chunks[0]

    def test_produces_multiple_chunks_for_long_text(self) -> None:
        # chunk_size=10 tokens ≈ 40 chars; force multiple chunks
        text = ". ".join(["This is sentence number " + str(i) for i in range(50)])
        chunks = chunk_text(text, chunk_size=10, chunk_overlap=2)
        assert len(chunks) > 1

    def test_all_chunks_non_empty(self) -> None:
        text = ". ".join(["Sentence " + str(i) for i in range(30)])
        chunks = chunk_text(text, chunk_size=20, chunk_overlap=4)
        assert all(c.strip() for c in chunks)

    def test_overlap_makes_chunks_share_content(self) -> None:
        # With overlap, consecutive chunks should share some content
        text = ". ".join(["word" + str(i) for i in range(100)])
        chunks_overlap = chunk_text(text, chunk_size=5, chunk_overlap=2)
        chunks_no_overlap = chunk_text(text, chunk_size=5, chunk_overlap=0)
        # Overlapping chunking produces more total content
        total_overlap = sum(len(c) for c in chunks_overlap)
        total_no_overlap = sum(len(c) for c in chunks_no_overlap)
        assert total_overlap >= total_no_overlap


# ---------------------------------------------------------------------------
# index_source — happy path and error paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_index_source_happy_path() -> None:
    from app.agent.indexer import index_source

    fake_text = ". ".join(["Sentence " + str(i) for i in range(20)])
    fake_embedding = [0.1] * 1536

    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.execute = AsyncMock()
    mock_conn.executemany = AsyncMock()
    mock_conn.close = AsyncMock()

    async def _mock_embed(**kwargs: object) -> MagicMock:
        n = len(kwargs.get("input", []))  # type: ignore[arg-type]
        resp = MagicMock()
        resp.data = [MagicMock(embedding=fake_embedding) for _ in range(n)]
        return resp

    mock_oai = AsyncMock()
    mock_oai.embeddings.create = AsyncMock(side_effect=_mock_embed)

    mock_storage = MagicMock()
    mock_storage.storage.from_.return_value.download.return_value = fake_text.encode()

    with (
        patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
        patch("pgvector.asyncpg.register_vector", AsyncMock()),
        patch("app.agent.indexer.AsyncOpenAI", return_value=mock_oai),
        patch("app.agent.indexer.create_client", return_value=mock_storage),
        patch("app.agent.indexer.settings") as mock_settings,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_key = "service-key"
        mock_settings.storage_bucket = "knowledge"

        await index_source(
            source_id="00000000-0000-0000-0000-000000000001",
            agent_id="00000000-0000-0000-0000-000000000002",
            user_id="00000000-0000-0000-0000-000000000003",
            storage_path="user/agent/file.txt",
            source_name="test.txt",
            source_type="txt",
            embedding_api_key="sk-test",
            chunk_size=10,
            chunk_overlap=2,
        )

    # Should have called execute for 'indexing', then 'ready'
    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("indexing" in c for c in calls)
    assert any("ready" in c for c in calls)
    # Should have inserted chunks
    assert mock_conn.executemany.called


@pytest.mark.asyncio
async def test_index_source_sets_error_on_extraction_failure() -> None:
    from app.agent.indexer import index_source

    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.execute = AsyncMock()
    mock_conn.close = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.storage.from_.return_value.download.side_effect = RuntimeError("Storage error")

    with (
        patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
        patch("app.agent.indexer.create_client", return_value=mock_storage),
        patch("app.agent.indexer.settings") as mock_settings,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_key = "service-key"
        mock_settings.storage_bucket = "knowledge"

        await index_source(
            source_id="00000000-0000-0000-0000-000000000001",
            agent_id="00000000-0000-0000-0000-000000000002",
            user_id="00000000-0000-0000-0000-000000000003",
            storage_path="path",
            source_name="f.txt",
            source_type="txt",
            embedding_api_key="sk-test",
            chunk_size=512,
            chunk_overlap=64,
        )

    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("error" in c for c in calls)


@pytest.mark.asyncio
async def test_index_source_sets_error_on_embed_failure() -> None:
    from app.agent.indexer import index_source

    fake_text = ". ".join(["Sentence " + str(i) for i in range(10)])

    mock_conn = AsyncMock()
    mock_conn.is_closed = MagicMock(return_value=False)
    mock_conn.execute = AsyncMock()
    mock_conn.close = AsyncMock()

    mock_storage = MagicMock()
    mock_storage.storage.from_.return_value.download.return_value = fake_text.encode()

    mock_oai = AsyncMock()
    mock_oai.embeddings.create = AsyncMock(side_effect=RuntimeError("OpenAI down"))

    with (
        patch("asyncpg.connect", AsyncMock(return_value=mock_conn)),
        patch("app.agent.indexer.AsyncOpenAI", return_value=mock_oai),
        patch("app.agent.indexer.create_client", return_value=mock_storage),
        patch("app.agent.indexer.settings") as mock_settings,
    ):
        mock_settings.database_url = "postgresql://test"
        mock_settings.supabase_url = "https://test.supabase.co"
        mock_settings.supabase_service_key = "service-key"
        mock_settings.storage_bucket = "knowledge"

        await index_source(
            source_id="00000000-0000-0000-0000-000000000001",
            agent_id="00000000-0000-0000-0000-000000000002",
            user_id="00000000-0000-0000-0000-000000000003",
            storage_path="path",
            source_name="f.txt",
            source_type="txt",
            embedding_api_key="sk-test",
            chunk_size=10,
            chunk_overlap=2,
        )

    calls = [str(c) for c in mock_conn.execute.call_args_list]
    assert any("error" in c for c in calls)
