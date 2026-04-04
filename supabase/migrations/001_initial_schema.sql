-- ─────────────────────────────────────────────────────────────────────────────
-- The Machine — Initial Schema
-- Run against Supabase Postgres or local Docker (pgvector/pgvector:pg16)
-- ─────────────────────────────────────────────────────────────────────────────

-- Enable pgvector for knowledge base embeddings
CREATE EXTENSION IF NOT EXISTS vector;

-- ─────────────────────────────────────────────────────────────────────────────
-- LLM Configs
-- Multiple named provider configs per user. One is marked is_default.
-- Credentials are stored AES-256-GCM encrypted — never in plaintext.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE llm_configs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id             UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name                TEXT NOT NULL,
    provider            TEXT NOT NULL,  -- openai|anthropic|gemini|grok|bedrock|azure|ollama|custom
    model               TEXT NOT NULL,
    is_default          BOOLEAN NOT NULL DEFAULT false,
    supports_tool_calls BOOLEAN NOT NULL DEFAULT true,
    context_window      INTEGER,
    config_enc          BYTEA NOT NULL,  -- AES-256-GCM encrypted JSON blob
    config_iv           BYTEA NOT NULL,  -- GCM nonce (12 bytes)
    tokens_used_today   INTEGER NOT NULL DEFAULT 0,
    budget_reset_at     TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);

-- Only one default config per user at the DB level
CREATE UNIQUE INDEX one_default_per_user ON llm_configs (user_id) WHERE is_default = true;

ALTER TABLE llm_configs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_llm_configs" ON llm_configs
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Agents
-- One or more named agents per user. Stores all block configurations.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE agents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL DEFAULT 'Untitled Agent',
    llm_config_id   UUID REFERENCES llm_configs(id) ON DELETE SET NULL,

    -- Instructions block
    instructions            TEXT NOT NULL DEFAULT '',
    persona_name            TEXT,
    response_style          TEXT NOT NULL DEFAULT 'balanced',  -- concise|balanced|verbose
    output_format           TEXT NOT NULL DEFAULT 'markdown',  -- markdown|plain_text|json|custom_schema
    output_schema           JSONB,
    response_language       TEXT NOT NULL DEFAULT 'en',
    show_reasoning          BOOLEAN NOT NULL DEFAULT false,

    -- Context block
    context_entries         JSONB NOT NULL DEFAULT '[]',
    auto_inject_datetime    BOOLEAN NOT NULL DEFAULT true,
    auto_inject_user_profile BOOLEAN NOT NULL DEFAULT true,
    context_render_as       TEXT NOT NULL DEFAULT 'yaml',      -- yaml|json|prose

    -- Memory block
    history_window          INTEGER NOT NULL DEFAULT 20,
    summarise_old_messages  BOOLEAN NOT NULL DEFAULT false,
    long_term_enabled       BOOLEAN NOT NULL DEFAULT false,
    memory_types            JSONB NOT NULL DEFAULT '["preferences","facts"]',
    max_memories            INTEGER NOT NULL DEFAULT 100,
    retention_days          INTEGER NOT NULL DEFAULT 90,

    -- Knowledge base block
    kb_top_k                INTEGER NOT NULL DEFAULT 4,
    kb_similarity_threshold FLOAT NOT NULL DEFAULT 0.7,
    kb_reranking            BOOLEAN NOT NULL DEFAULT false,
    kb_show_sources         BOOLEAN NOT NULL DEFAULT true,
    kb_chunk_size           INTEGER NOT NULL DEFAULT 512,
    kb_chunk_overlap        INTEGER NOT NULL DEFAULT 64,
    embedding_api_key_enc   BYTEA,  -- encrypted, for providers without embedding support
    embedding_api_key_iv    BYTEA,

    -- Guardrails block
    max_iterations              INTEGER NOT NULL DEFAULT 5,
    on_max_iterations           TEXT NOT NULL DEFAULT 'return_partial',  -- return_partial|fail_with_message|ask_user
    max_tool_calls_per_run      INTEGER NOT NULL DEFAULT 20,
    max_tokens_per_run          INTEGER NOT NULL DEFAULT 8000,
    topic_restrictions          JSONB NOT NULL DEFAULT '[]',
    allow_clarifying_questions  BOOLEAN NOT NULL DEFAULT true,
    pii_detection               BOOLEAN NOT NULL DEFAULT false,
    safe_tool_mode              BOOLEAN NOT NULL DEFAULT false,

    -- Output / response format
    verbosity               TEXT NOT NULL DEFAULT 'balanced',  -- minimal|balanced|detailed
    include_citations       BOOLEAN NOT NULL DEFAULT true,
    strip_thinking          BOOLEAN NOT NULL DEFAULT true,
    response_length_limit   INTEGER,

    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_agents" ON agents
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Agent Tools
-- One row per tool per agent. Credentials encrypted same as llm_configs.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE agent_tools (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

    tool_key    TEXT NOT NULL,   -- calculator|current_datetime|url_reader|wikipedia_search|web_search|custom
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    parameters  JSONB NOT NULL DEFAULT '{}',

    enabled                 BOOLEAN NOT NULL DEFAULT true,
    timeout_seconds         INTEGER NOT NULL DEFAULT 15,
    max_calls_per_run       INTEGER NOT NULL DEFAULT 5,
    retry_on_failure        BOOLEAN NOT NULL DEFAULT true,
    show_result_in_chat     BOOLEAN NOT NULL DEFAULT true,
    result_truncation_chars INTEGER NOT NULL DEFAULT 2000,

    -- Encrypted credentials (null for zero-auth tools)
    credentials_enc BYTEA,
    credentials_iv  BYTEA,

    -- For custom HTTP tools
    endpoint_url TEXT,

    sort_order  INTEGER NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ DEFAULT now(),
    updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agent_tools ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_agent_tools" ON agent_tools
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Agent Traces
-- One row per agent run (per message). Linked to agent + llm_config used.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE agent_traces (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID REFERENCES agents(id) ON DELETE SET NULL,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    llm_config_id   UUID REFERENCES llm_configs(id) ON DELETE SET NULL,
    user_message    TEXT NOT NULL,
    trace_json      JSONB NOT NULL,
    created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agent_traces ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_traces" ON agent_traces
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge Sources
-- One row per uploaded file, URL, or text paste per agent.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE knowledge_sources (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,   -- file|url|text
    source_url      TEXT,
    storage_path    TEXT,            -- Supabase Storage path for uploaded files
    file_size_bytes INTEGER,
    chunk_count     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|indexing|ready|error
    error_message   TEXT,
    created_at      TIMESTAMPTZ DEFAULT now(),
    updated_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_knowledge_sources" ON knowledge_sources
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Knowledge Chunks
-- One row per text chunk, with pgvector embedding.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE knowledge_chunks (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_id   UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    embedding   vector(1536),    -- text-embedding-3-small dimensions
    chunk_index INTEGER NOT NULL,
    metadata    JSONB,           -- page number, section title, source URL, etc.
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- IVFFlat index for fast approximate nearest-neighbour cosine similarity search
CREATE INDEX ON knowledge_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_knowledge_chunks" ON knowledge_chunks
    FOR ALL USING (auth.uid() = user_id);

-- ─────────────────────────────────────────────────────────────────────────────
-- Agent Memories
-- Long-term memories the agent retains across sessions.
-- ─────────────────────────────────────────────────────────────────────────────

CREATE TABLE agent_memories (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id    UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    content     TEXT NOT NULL,
    memory_type TEXT NOT NULL DEFAULT 'fact',  -- fact|preference|decision|correction
    expires_at  TIMESTAMPTZ,  -- null = never expires
    created_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agent_memories ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_memories" ON agent_memories
    FOR ALL USING (auth.uid() = user_id);
