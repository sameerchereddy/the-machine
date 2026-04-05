# The Machine — Design Document

> A multi-provider AI agent platform. Bring your own LLM, configure it once, and run a supervisor agent that reasons across tools with full traceability.

---

## 1. Vision

Most agent demos are hardcoded to one LLM and one use case. **The Machine** is different:

- Any user can log in, configure their preferred LLM provider (OpenAI, Claude, Gemini, Grok, Bedrock, Azure, Ollama), and immediately run a production-quality supervisor agent against it.
- The agent architecture is the showcase — a true multi-step ReAct loop with dynamic tool selection, sub-agent delegation, and full trace visibility.
- The platform is the proof — auth, encrypted credential storage, and a clean provider abstraction layer that shows engineering depth beyond "I called the OpenAI API."

---

## 1a. Competitive Positioning

Researched 12 platforms: Flowise, Langflow, Dify, AutoGPT, SuperAGI, Botpress, Bisheng, n8n, Stack AI, LangGraph + LangSmith, Helicone, W&B Weave.

### The Landscape in One Paragraph

The multi-provider agent space splits into three camps: **visual builders** (Flowise, Langflow, Dify, n8n) that delegate the agent loop to LangChain and treat observability as an external integration; **observability tools** (LangSmith, Helicone, W&B Weave) that bolt onto whatever agent code you already have; and **framework libraries** (LangGraph) that require you to write the agent yourself in code with no product layer on top. None of them solve the full problem end-to-end: secure multi-provider credential management + a purpose-built agent loop + first-party native trace visibility — in a single coherent product.

### What Everyone Gets Wrong

| Gap | Who has it | Detail |
|---|---|---|
| Credential security | All visual builders | Every platform accepts user API keys but none document per-user encryption at rest. Keys are stored in a credential store with no described security model beyond access control. |
| Delegated agent loop | Flowise, Langflow, Dify, n8n | The "agent" is assembled by wiring LangChain components. There is no custom ReAct implementation — the loop is a black box inside LangChain. |
| Outsourced observability | Dify, Flowise, Langflow | Traces are delegated to Langfuse or LangSmith — external paid services. There is no first-party trace stored in the product's own database. |
| Framework-not-product gap | LangGraph + LangSmith | LangGraph is a code library. LangSmith is a separate paid SaaS add-on. Neither constitutes a product a user can log into. |
| No provider reliability layer | All visual builders | None implement fallback provider, automatic tool-call compatibility check on credential save, per-provider token budget, or configurable retry with exponential backoff at the provider adapter layer. |

### What The Machine Does Differently

**1. Production-grade BYOK security — the gap no one has filled**
Per-user AES-256-GCM envelope encryption where the key is derived from `HMAC-SHA256(SERVER_SECRET, user_id)`. DB-level Row Level Security so a valid JWT alone cannot read another user's keys. Masked key display, ping-to-validate before save. No other platform in this space has documented this level of credential security design.

**2. A custom ReAct loop — not a LangChain wrapper**
The agent loop is written from scratch. Every Reason → Act → Observe iteration is explicit, auditable, and independent of framework version drift. The loop itself is what demonstrates engineering depth — not configuration of LangChain components.

**3. Native first-party traces — not a monitoring integration**
Every agent run produces a structured JSON document capturing each iteration: reasoning text, tools called, tool inputs/outputs, sufficiency decision, token usage, latency. Stored as a row in the user's own Supabase database. Viewable in the product UI. Not piped to Langfuse, LangSmith, or any external service.

**4. Provider reliability that the visual builders assume you'll solve yourself**
Fallback provider chain (switch to a second LLM if the first fails, recorded in the trace), automatic tool-call compatibility detection on ping, per-provider daily token budget with hard stop, configurable timeout and exponential-backoff retry — all baked into the provider adapter layer, not left to the user.

**5. The combination that requires four products elsewhere**
The closest equivalent to The Machine would be: Dify (multi-provider BYOK + agent) + LangSmith (trace) + a custom encryption service (credential security) + a custom reliability layer (fallback + retry + budget). The Machine collapses all four into one.

### What The Machine Does Not Have (and is honest about)

| Feature | Who has it | Our position |
|---|---|---|
| Visual workflow builder | Flowise, Langflow, Dify, n8n | Not planned — The Machine is a configured supervisor agent, not a composable workflow tool |
| 50+ built-in tools | Dify | v1 ships with 5 tools; extensible in roadmap |
| Evals / quality measurement | LangSmith, W&B Weave | Not in v1 scope |
| Multi-tenant production deployment | Dify, Flowise, Botpress | v1 is per-user; team/org is future roadmap |
| LLM fine-tuning | Bisheng | Out of scope entirely |

### README Positioning (informed by this research)

The one-paragraph differentiator for the README:

> "Flowise, Langflow, and Dify let you build agents by wiring LangChain components together. LangGraph lets you write the loop in code. LangSmith observes what's happening — for a fee, separately. The Machine is none of these. It's a single product where you bring your own LLM credentials (any of 8 providers), they're encrypted per-user with AES-256-GCM, and a purpose-built ReAct loop runs against them — with every reasoning step, tool call, and decision stored as a first-class trace in your own database. No LangChain. No external observability service. No vendor picking your model."

---

## 2. Architecture Overview

```
┌─────────────────────────────────────────────────────┐
│                    Browser (React)                   │
│  /login   /setup   /agent   /traces                 │
└──────────────────────┬──────────────────────────────┘
                       │ HTTPS + WebSocket
┌──────────────────────▼──────────────────────────────┐
│                  FastAPI Backend                      │
│                                                      │
│  auth middleware (JWT via Supabase)                  │
│  /api/llm/configs       — LLM provider configs       │
│  /api/agents            — agent CRUD + tool/KB mgmt  │
│  WS /api/agents/:id/run — streaming agent session    │
│  /api/traces            — trace storage + retrieval  │
└──────┬───────────────────────────┬───────────────────┘
       │                           │
┌──────▼──────┐           ┌────────▼────────┐
│  Supervisor  │           │   Supabase       │
│  Agent       │           │   - Auth (JWT)   │
│  (ReAct loop)│           │   - Postgres DB  │
└──────┬───────┘           │   - RLS policies │
       │                   └─────────────────┘
┌──────▼───────────────────────────────────────┐
│              LLM Abstraction Layer            │
│         (Custom Provider Adapter)             │
│  OpenAI · Claude · Gemini · Grok              │
│  Bedrock · Azure OpenAI · Ollama · Custom     │
└──────────────────────────────────────────────┘
```

---

## 3. Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| Frontend | React + TypeScript + Vite | Fast, typed, familiar |
| UI components | shadcn/ui + Tailwind | Clean, not opinionated |
| Backend | FastAPI (Python) | Async, typed, good WebSocket support |
| Auth | Supabase Auth | Email/password + Google SSO out of the box |
| Database | Supabase Postgres + pgvector | One Postgres DB for both relational tables and vector search — pgvector is a built-in extension, no separate vector DB needed |
| LLM routing | Custom provider adapter | Thin wrapper over each provider's official SDK — no third-party routing dependency |
| Encryption | Python `cryptography` (AES-GCM) | Industry standard, simple API |
| Agent loop | Custom ReAct (Python) | The showcase — not delegated to a framework |

---

## 4. Authentication

### Flows

**Email / Password**
```
User submits credentials → Supabase Auth → JWT (access + refresh tokens)
JWT stored in httpOnly cookie (not localStorage — XSS protection)
FastAPI middleware validates JWT on every request
```

**Google SSO**
```
User clicks "Continue with Google" → Supabase OAuth redirect → Google consent
→ Supabase callback → JWT issued → same cookie flow
```

### Session Management
- Access token: 1 hour TTL
- Refresh token: 30 days, rotated on use
- Backend validates every request against Supabase JWT secret — no DB roundtrip per request

---

## 5. LLM Configuration

### Supported Providers

| Provider | Required fields | Model selection |
|---|---|---|
| OpenAI | API key, model | Dropdown of known models + custom freetext |
| Anthropic (Claude) | API key, model | Dropdown of known models + custom freetext |
| Google Gemini | API key, model | Dropdown of known models + custom freetext |
| xAI (Grok) | API key, model, base URL | Freetext |
| AWS Bedrock | AWS access key, secret key, region, model ID | Dropdown of known model IDs + custom freetext |
| Azure OpenAI | Endpoint, API key, deployment name, API version | Freetext |
| Ollama (local) | Base URL (e.g. `http://localhost:11434`), model name | Freetext — model must be pulled locally first |
| Custom (OpenAI-compatible) | Base URL, API key, model name | Freetext — covers Groq, Together AI, Mistral, Perplexity, Fireworks, etc. |

**Note on Ollama ping errors:** If the model isn't pulled, ping returns a specific error: `"Model not found — run 'ollama pull <model>' first"` rather than a generic connection error.

### Full Config Schema

Each user can save multiple named LLM configs. One is designated as default. Fields are split into v1 (built now) and future (designed for, not yet built).

```jsonc
{
  // --- Identity ---
  "name": "Fast Claude",         // user-defined label for this config
  "is_default": true,            // one config per user is the default for new sessions

  // --- Credentials (always provider-specific) ---
  "provider": "openai",          // "openai" | "anthropic" | "gemini" | "grok" | "bedrock" | "azure" | "ollama" | "custom"
  "model": "gpt-4o",
  "api_key": "sk-...",           // encrypted at rest
  "base_url": null,              // required for Grok, Azure, Ollama, Custom

  // --- Model behaviour (v1) ---
  "temperature": 0.7,            // 0.0–1.0, default 0.7
  "max_tokens": 2048,            // max output tokens per call
  "context_window": 128000,      // model's input token limit — used by agent loop to avoid overflow

  // --- Tool calling (v1) ---
  "supports_tool_calls": true,   // set automatically during ping — agent requires this to be true

  // --- Reliability (v1) ---
  "timeout_seconds": 30,         // abort request after N seconds
  "max_retries": 2,              // retry on transient errors (429, 5xx, timeout)

  // --- Fallback (v1) ---
  "fallback_config_id": "uuid",  // references another saved config by ID — null = no fallback

  // --- Cost guardrails (v1) ---
  "daily_token_budget": 100000,  // hard stop after N tokens/day tracked per config, null = unlimited

  // --- Future ---
  "system_prompt": null,         // default system prompt prepended to every call
  "requests_per_minute": null,   // client-side RPM throttle
  "tokens_per_minute": null,     // client-side TPM throttle
  "cache_exact_matches": false,  // skip LLM call for identical prompts
  "log_to_langsmith": false,     // pipe traces to LangSmith
  "log_to_helicone": false       // pipe traces to Helicone
}
```

### What Each Setting Does

**Model behaviour**

| Field | Effect | Why it matters |
|---|---|---|
| `temperature` | Controls randomness of output | Lower = more consistent reasoning, higher = more creative |
| `max_tokens` | Caps response length | Prevents runaway cost on long generations |

**Reliability**

| Field | Effect | Why it matters |
|---|---|---|
| `timeout_seconds` | Aborts request if LLM is too slow | Prevents the agent hanging on a slow provider |
| `max_retries` | Auto-retries on rate limit (429), timeout, server error | Resilience without extra code in the agent loop |
| `fallback_provider` | Transparent failover to a second LLM | If Claude is down, the agent silently continues on GPT-4o. Recorded in the trace. |

**Cost guardrails**

| Field | Effect | Why it matters |
|---|---|---|
| `daily_token_budget` | Hard stop once N tokens consumed today | Prevents runaway spend on a shared API key |

### Config Test (Ping)
Before saving, the user hits "Test Connection". The backend:
1. Sends a minimal completion request (`"Say hi"`, max 5 tokens) using the provided credentials
2. Checks whether the model supports tool/function calling — **required for the agent to work**
3. Returns `{ ok: true, latency_ms: 312, model: "gpt-4o", supports_tool_calls: true, context_window: 128000 }` or a structured error
4. If `supports_tool_calls: false`, the UI shows a warning: "This model doesn't support tool calling — the agent will not work with it"
5. On success, user confirms → config is encrypted and saved; `supports_tool_calls` and `context_window` are stored automatically
6. Fallback config (if set) is pinged independently in the same call

### What Is Shown vs. Hidden After Saving
Once saved, the config appears in a list with its name, provider, model, and default badge. The UI also shows timeout, temperature, budget, and whether tool calling is supported. **The API key is never returned to the client** — the backend only exposes `"api_key": "sk-...***"` (masked). To update, the user must re-enter the full key.

---

### v1 vs. Future: LLM Config

| Feature | v1 | Future |
|---|---|---|
| All 7 providers + Custom (OpenAI-compatible) | ✅ | |
| Multiple named configs per user | ✅ | |
| Default config + per-session switching | ✅ | |
| Model dropdown (known models) + freetext | ✅ | |
| temperature, max_tokens | ✅ | |
| context_window (auto-detected on ping) | ✅ | |
| Tool calling compatibility check on ping | ✅ | |
| timeout, max_retries | ✅ | |
| Fallback by saved config reference | ✅ | |
| Daily token budget (tracked per config) | ✅ | |
| Custom system prompt | | ✅ |
| RPM / TPM throttling | | ✅ |
| Exact-match caching | | ✅ |
| LangSmith / Helicone integration | | ✅ |

---

## 5a. LLM Provider Adapter

Rather than depending on LiteLLM (which has had reliability and maintenance concerns), The Machine uses a thin custom adapter written directly against each provider's official Python SDK.

### Why not LiteLLM

LiteLLM is a convenient abstraction but introduces a third-party dependency between the agent and the LLMs it calls. For a showcase project where the provider layer is itself part of the demonstration, owning that layer is the right call.

### Provider Groups

```
OpenAI-compatible (one client, different base_url)
  openai   → openai.AsyncOpenAI()
  grok     → openai.AsyncOpenAI(base_url="https://api.x.ai/v1")
  ollama   → openai.AsyncOpenAI(base_url="http://localhost:11434/v1")
  custom   → openai.AsyncOpenAI(base_url=user_base_url)
  azure    → openai.AsyncAzureOpenAI(azure_endpoint=..., api_version=...)

Own SDK
  anthropic → anthropic.AsyncAnthropic()
  gemini    → google.generativeai (AsyncGenerativeModel)
  bedrock   → aiobotocore → bedrock-runtime Converse API
```

### File Structure

```
backend/app/llm/
  __init__.py               — public exports: build_adapter, types
  types.py                  — LLMResponse, StreamChunk, ToolCall, Usage
  adapter.py                — BaseProvider, ProviderWithRetry, get_provider, build_adapter
  providers/
    openai_compat.py        — OpenAICompatProvider + AzureProvider
    anthropic.py            — AnthropicProvider
    gemini.py               — GeminiProvider
    bedrock.py              — BedrockProvider
```

### Normalised Interface

Every provider exposes the same three methods:

| Method | Returns | Notes |
|---|---|---|
| `complete(messages, tools, ...)` | `LLMResponse` | Single-turn, blocking |
| `stream(messages, tools, ...)` | `AsyncGenerator[StreamChunk]` | Streaming, yields deltas + tool calls + usage |
| `embed(texts)` | `list[list[float]]` | Embeddings for KB — raises `NotImplementedError` for providers without embedding support |

All tool calling uses **OpenAI function-calling format** as the canonical input. Each provider adapter converts to its own format internally (Anthropic `input_schema`, Gemini `FunctionDeclaration`, Bedrock `toolSpec`).

### Retry + Fallback

The agent never calls a provider directly — it always goes through `ProviderWithRetry`:

```python
adapter = build_adapter(primary_config, fallback_config)
response = await adapter.complete(messages, tools=tools)
```

`ProviderWithRetry` handles:
- Timeout via `asyncio.wait_for`
- Exponential backoff retry on rate limits (429) and transient server errors (5xx)
- Transparent fallback to a second provider after retries are exhausted
- All of this is recorded in the agent trace

### Usage

```python
from app.llm import build_adapter

# decrypted configs come from the encryption layer
adapter = build_adapter(primary_config, fallback_config=None)

# non-streaming
response = await adapter.complete(messages, tools=tools)
print(response.content, response.tool_calls, response.usage)

# streaming
async for chunk in adapter.stream(messages, tools=tools):
    if chunk.delta:
        print(chunk.delta, end="", flush=True)
    if chunk.tool_calls:
        # agent loop handles tool execution
        pass

# embeddings (for KB retrieval)
vectors = await adapter.embed(["chunk text 1", "chunk text 2"])
```

---

## 6. Credential Encryption

### Threat Model
- Protect against: DB breach, rogue DB admin, leaked DB snapshot
- Does not protect against: full server compromise (attacker has both DB and server secret)
- Acceptable tradeoff for this architecture tier

### Approach: Envelope Encryption

```
SERVER_SECRET  (env var, never in DB)
user_id        (known at request time from JWT)

encryption_key = HMAC-SHA256(SERVER_SECRET, user_id)
ciphertext     = AES-256-GCM-Encrypt(plaintext_api_key, encryption_key)
```

Each user gets a unique derived key. Even if `SERVER_SECRET` leaks, an attacker needs the specific `user_id` to decrypt a specific user's config. Even if the DB leaks in full, it's useless without `SERVER_SECRET`.

### Storage

```sql
-- Only the encrypted blob is stored
-- The plaintext key never touches the DB
CREATE TABLE llm_configs (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id              UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name                 TEXT NOT NULL,          -- user-defined label, e.g. "Fast Claude"
  provider             TEXT NOT NULL,          -- 'openai' | 'anthropic' | 'gemini' | 'grok' | 'bedrock' | 'azure' | 'ollama' | 'custom'
  model                TEXT NOT NULL,
  is_default           BOOLEAN NOT NULL DEFAULT false,
  supports_tool_calls  BOOLEAN NOT NULL DEFAULT true,   -- set on ping
  context_window       INTEGER,                          -- set on ping, null if unknown
  config_enc           BYTEA NOT NULL,                   -- AES-GCM encrypted JSON blob
  config_iv            BYTEA NOT NULL,                   -- GCM nonce (random, 12 bytes)
  tokens_used_today    INTEGER NOT NULL DEFAULT 0,       -- reset daily per config
  budget_reset_at      TIMESTAMPTZ,                      -- when the daily counter was last reset
  created_at           TIMESTAMPTZ DEFAULT now(),
  updated_at           TIMESTAMPTZ DEFAULT now()
);

-- Enforce only one default per user at the DB level
CREATE UNIQUE INDEX one_default_per_user ON llm_configs (user_id) WHERE is_default = true;
```

### Row Level Security

```sql
-- Users can only access their own rows — enforced at DB level
ALTER TABLE llm_configs ENABLE ROW LEVEL SECURITY;

CREATE POLICY "user_owns_config" ON llm_configs
  FOR ALL USING (auth.uid() = user_id);
```

Two independent layers: app-level encryption + DB-level RLS. A valid JWT alone is not enough — the server must also decrypt.

---

## 7. Supervisor Agent Architecture

This is the centrepiece of the showcase.

### ReAct Loop (multi-step, not single-pass)

```
User message
     │
     ▼
┌─────────────────────────────────────────────┐
│  REASON: What do I need to answer this?     │  ← LLM call
│  → Identify sub-questions                   │
│  → Select tools needed                      │
└──────────────────┬──────────────────────────┘
                   │
     ┌─────────────▼──────────────┐
     │  ACT: Execute tool calls   │  ← parallel where possible
     └─────────────┬──────────────┘
                   │
     ┌─────────────▼──────────────┐
     │  OBSERVE: Are results      │
     │  sufficient to answer?     │  ← LLM call
     │  NO → loop back to REASON  │
     │  YES → proceed             │
     └─────────────┬──────────────┘
                   │
     ┌─────────────▼──────────────┐
     │  RESPOND: Synthesize       │  ← LLM call (streaming)
     └────────────────────────────┘
```

Key difference from the naive approach: the agent can **loop** — if tool results raise new questions, it reasons again rather than forcing an answer from incomplete data. Max iterations are capped (default: 5) to prevent runaway loops.

### Trace Visibility

Every agent run produces a structured trace:

```json
{
  "trace_id": "abc123",
  "user_message": "...",
  "iterations": [
    {
      "step": 1,
      "reasoning": "I need X and Y to answer this...",
      "tools_called": ["tool_a", "tool_b"],
      "tool_results": { "tool_a": {...}, "tool_b": {...} },
      "sufficient": false
    },
    {
      "step": 2,
      "reasoning": "Now I have X and Y, I can answer...",
      "tools_called": [],
      "sufficient": true
    }
  ],
  "final_answer": "...",
  "total_llm_calls": 3,
  "total_tokens": 1842,
  "duration_ms": 4120
}
```

This trace is stored and viewable in the UI under `/traces`. It makes the agent's reasoning **transparent and auditable** — which is the whole point of the showcase.

---

## 7a. Default Built-in Tools

These are the tools available out of the box. They are the minimum needed for the ReAct loop to demonstrate meaningful multi-step reasoning. Every tool is pre-configured with a name and description the agent sees — the user can override both.

### Tier 1 — Zero Auth (always available, no credentials required)

| Tool | Key | What it does | Example use |
|---|---|---|---|
| Calculator | `calculator` | Evaluates math expressions safely — arithmetic, percentages, unit conversions | "What's 15% tip on $84?" → agent calls calculator |
| Current Date & Time | `current_datetime` | Returns current UTC datetime and user's timezone offset | "What day is it?" / date arithmetic |
| URL Reader | `url_reader` | Fetches a URL and extracts clean text content (strips HTML/JS) | "Summarise this article: [url]" |
| Wikipedia Search | `wikipedia_search` | Searches Wikipedia and returns the top article summary — no API key, uses the public Wikipedia API | "Who invented the transistor?" |

### Tier 2 — Requires User API Key (user provides credentials in tool config)

| Tool | Key | Provider | What it does | Why this one |
|---|---|---|---|---|
| Web Search | `web_search` | Tavily | Real-time web search returning ranked results with snippets | Most impactful demo tool. Tavily has a free tier and a simple single-key setup. Serper or Brave accepted as alternatives. |

### Tier 3 — Future (not in v1)

| Tool | Key | Reason deferred |
|---|---|---|
| Code Interpreter | `code_interpreter` | Requires sandboxed execution environment — security surface too large for v1 |
| Image Generation | `image_gen` | Separate provider auth flow, out of scope for v1 |
| Send Email | `send_email` | Requires SMTP / SendGrid config, deferred |
| Database Query | `db_query` | User-provided connection string, security review needed |

---

### What Multi-Step Reasoning Looks Like With These Tools

A query like **"How much would a 20% tip be on a meal costing the same as today's BTC price in USD divided by 1000?"** forces the agent to:

1. Call `web_search` → get current BTC price
2. Call `calculator` → divide by 1000
3. Call `calculator` → calculate 20% tip
4. Synthesise answer

This is the ReAct loop in action — three tool calls across two tools, chained by reasoning. With just Tier 1 + web search, the showcase is complete.

---

### Tool Schema (what each tool exposes to the agent)

Every tool is described to the LLM as a function. Example for `calculator`:

```json
{
  "name": "calculator",
  "description": "Evaluates a mathematical expression and returns the result. Use this for any arithmetic, percentage calculations, or unit conversions. Input must be a valid math expression as a string.",
  "parameters": {
    "type": "object",
    "properties": {
      "expression": {
        "type": "string",
        "description": "The math expression to evaluate. E.g. '(84 * 0.15)' or '100 / 3'"
      }
    },
    "required": ["expression"]
  }
}
```

The description field is the most important lever on tool usage quality — a bad description means the agent calls the wrong tool or formats inputs incorrectly. All default tool descriptions are carefully written and tested. Users can override them per agent.

---

## 8. Data Model

```
auth.users               (managed by Supabase)
  └── llm_configs        (multiple named LLM provider configs per user)
  └── agents             (one or more saved agents per user)
        └── agent_tools  (tools configured for each agent, with encrypted credentials)
        └── agent_traces (one row per agent run, linked to the agent that ran)
  └── knowledge_sources  (uploaded files / URLs per agent)
        └── knowledge_chunks (chunked + embedded text, stored with pgvector)
```

---

### agents

Stores everything about a saved agent — its name and all block configurations.

```sql
CREATE TABLE agents (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id          UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name             TEXT NOT NULL DEFAULT 'Untitled Agent',
  llm_config_id    UUID REFERENCES llm_configs(id) ON DELETE SET NULL,

  -- Instructions block
  instructions     TEXT NOT NULL DEFAULT '',        -- system prompt, markdown
  persona_name     TEXT,
  response_style   TEXT NOT NULL DEFAULT 'balanced', -- 'concise' | 'balanced' | 'verbose'
  output_format    TEXT NOT NULL DEFAULT 'markdown', -- 'markdown' | 'plain_text' | 'json' | 'custom_schema'
  output_schema    JSONB,                            -- populated when output_format = 'json'
  response_language TEXT NOT NULL DEFAULT 'en',
  show_reasoning   BOOLEAN NOT NULL DEFAULT false,

  -- Context block
  context_entries  JSONB NOT NULL DEFAULT '[]',      -- [{key, value}]
  auto_inject_datetime    BOOLEAN NOT NULL DEFAULT true,
  auto_inject_user_profile BOOLEAN NOT NULL DEFAULT true,
  context_render_as TEXT NOT NULL DEFAULT 'yaml',    -- 'yaml' | 'json' | 'prose'

  -- Memory block
  history_window         INTEGER NOT NULL DEFAULT 20,
  summarise_old_messages BOOLEAN NOT NULL DEFAULT false,
  long_term_enabled      BOOLEAN NOT NULL DEFAULT false,
  memory_types           JSONB NOT NULL DEFAULT '["preferences","facts"]',
  max_memories           INTEGER NOT NULL DEFAULT 100,
  retention_days         INTEGER NOT NULL DEFAULT 90,

  -- Knowledge base block
  kb_top_k              INTEGER NOT NULL DEFAULT 4,
  kb_similarity_threshold FLOAT NOT NULL DEFAULT 0.7,
  kb_reranking          BOOLEAN NOT NULL DEFAULT false,
  kb_show_sources       BOOLEAN NOT NULL DEFAULT true,
  kb_chunk_size         INTEGER NOT NULL DEFAULT 512,
  kb_chunk_overlap      INTEGER NOT NULL DEFAULT 64,

  -- Guardrails block
  max_iterations        INTEGER NOT NULL DEFAULT 5,
  on_max_iterations     TEXT NOT NULL DEFAULT 'return_partial', -- 'return_partial' | 'fail_with_message' | 'ask_user'
  max_tool_calls_per_run INTEGER NOT NULL DEFAULT 20,
  max_tokens_per_run    INTEGER NOT NULL DEFAULT 8000,
  topic_restrictions    JSONB NOT NULL DEFAULT '[]',  -- [string]
  allow_clarifying_questions BOOLEAN NOT NULL DEFAULT true,
  pii_detection         BOOLEAN NOT NULL DEFAULT false,
  safe_tool_mode        BOOLEAN NOT NULL DEFAULT false,

  created_at  TIMESTAMPTZ DEFAULT now(),
  updated_at  TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_agents" ON agents
  FOR ALL USING (auth.uid() = user_id);
```

---

### agent_tools

Each row is one tool configured for a specific agent. Tool credentials are encrypted the same way as LLM API keys.

```sql
CREATE TABLE agent_tools (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,

  tool_key     TEXT NOT NULL,   -- internal identifier: 'web_search', 'calculator', 'custom', etc.
  name         TEXT NOT NULL,   -- name the agent sees — overridable
  description  TEXT NOT NULL,   -- what the agent reads to decide when to call this tool
  parameters   JSONB NOT NULL DEFAULT '{}',  -- JSON schema for tool inputs

  enabled      BOOLEAN NOT NULL DEFAULT true,
  timeout_seconds     INTEGER NOT NULL DEFAULT 15,
  max_calls_per_run   INTEGER NOT NULL DEFAULT 5,
  retry_on_failure    BOOLEAN NOT NULL DEFAULT true,
  show_result_in_chat BOOLEAN NOT NULL DEFAULT true,
  result_truncation_chars INTEGER NOT NULL DEFAULT 2000,

  -- Encrypted credentials (same envelope encryption as llm_configs)
  credentials_enc  BYTEA,   -- null for zero-auth tools
  credentials_iv   BYTEA,

  -- For custom HTTP tools
  endpoint_url  TEXT,   -- null for built-in tools

  sort_order   INTEGER NOT NULL DEFAULT 0,  -- display order in builder
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agent_tools ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_agent_tools" ON agent_tools
  FOR ALL USING (auth.uid() = user_id);
```

---

### agent_traces

One row per agent run. Now linked to the specific agent that produced it.

```sql
CREATE TABLE agent_traces (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id     UUID REFERENCES agents(id) ON DELETE SET NULL,  -- null if agent was deleted
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  user_message TEXT NOT NULL,
  llm_config_id UUID REFERENCES llm_configs(id) ON DELETE SET NULL,  -- snapshot of which LLM was used
  trace_json   JSONB NOT NULL,
  created_at   TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE agent_traces ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_traces" ON agent_traces
  FOR ALL USING (auth.uid() = user_id);
```

---

### knowledge_sources + knowledge_chunks (pgvector)

The Knowledge Base block is backed by Supabase's built-in `pgvector` extension — no external vector DB needed.

```sql
CREATE EXTENSION IF NOT EXISTS vector;

-- One row per uploaded file, URL, or text paste
CREATE TABLE knowledge_sources (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  name         TEXT NOT NULL,
  source_type  TEXT NOT NULL,   -- 'file' | 'url' | 'text'
  source_url   TEXT,            -- populated for 'url' sources
  file_size_bytes INTEGER,
  chunk_count  INTEGER NOT NULL DEFAULT 0,
  status       TEXT NOT NULL DEFAULT 'pending',  -- 'pending' | 'indexing' | 'ready' | 'error'
  error_message TEXT,
  created_at   TIMESTAMPTZ DEFAULT now(),
  updated_at   TIMESTAMPTZ DEFAULT now()
);

-- One row per chunk — this is what gets searched
CREATE TABLE knowledge_chunks (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id    UUID NOT NULL REFERENCES knowledge_sources(id) ON DELETE CASCADE,
  agent_id     UUID NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
  user_id      UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  content      TEXT NOT NULL,
  embedding    vector(1536),    -- dimensions match text-embedding-3-small
  chunk_index  INTEGER NOT NULL,
  metadata     JSONB,           -- page number, section title, source URL, etc.
  created_at   TIMESTAMPTZ DEFAULT now()
);

-- IVFFlat index for fast approximate nearest-neighbour search
CREATE INDEX ON knowledge_chunks
  USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

ALTER TABLE knowledge_sources ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_sources" ON knowledge_sources
  FOR ALL USING (auth.uid() = user_id);

ALTER TABLE knowledge_chunks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "user_owns_chunks" ON knowledge_chunks
  FOR ALL USING (auth.uid() = user_id);
```

**Embedding model**: `text-embedding-3-small` (OpenAI, 1536 dimensions). Providers without native embedding support (Anthropic, Grok, Ollama, Bedrock) require a separate OpenAI key used only for embeddings. This is stored as an optional `embedding_api_key` field in the `agents` table (encrypted). The ping endpoint checks embedding support for the selected LLM and prompts for the embedding key if missing and the KB block is enabled.

**File storage**: uploaded files are stored in **Supabase Storage** in a private bucket named `knowledge`. Files are stored at path `{user_id}/{agent_id}/{source_id}/{filename}`. The bucket is private — files are only accessible via signed URLs generated server-side.

**Indexing pipeline** (async — does not block the upload response):
```
POST /api/agents/:id/knowledge
  → validate file type + size (max 20MB, pdf/txt/md/docx)
  → upload raw file to Supabase Storage
  → insert knowledge_sources row with status = 'pending'
  → return { source_id, status: 'pending' } immediately
  → FastAPI BackgroundTask kicks off:
      → download file from Storage
      → extract text (pypdf / python-docx / raw text)
      → chunk text (chunk_size, chunk_overlap from agent config)
      → batch embed chunks via OpenAI embeddings API
      → insert knowledge_chunks rows with embedding vectors
      → update knowledge_sources status = 'ready' (or 'error')
```
Client polls `GET /api/agents/:id/knowledge` to check status. The KB block shows "Indexing..." until status = 'ready'.

**Retrieval flow** (happens inside the agent's `knowledge_search` tool):
```
query text
  → embed with text-embedding-3-small
  → cosine similarity search against knowledge_chunks for this agent
  → filter by similarity >= kb_similarity_threshold
  → return top kb_top_k chunks
  → (optional) reranking pass
  → inject chunks into LLM context with source citations
```

**Long-term memory write mechanism**: The agent has access to a `save_memory` tool (always enabled when `long_term_enabled = true`). The agent calls it explicitly when it identifies something worth remembering. Additionally, after each session ends, a lightweight extraction pass runs over the conversation and saves any new facts the agent flagged. Memories are stored in an `agent_memories` table (user_id, agent_id, content TEXT, type TEXT, created_at).

---

## 9. API Contract

```
POST /api/auth/login          — email + password → JWT (set cookie)
POST /api/auth/logout         — clear cookie
GET  /api/auth/me             — current user info

POST /api/llm/configs              — create a new named LLM config
GET  /api/llm/configs              — list all user's configs (provider + model, NOT keys)
GET  /api/llm/configs/:id          — get one config (masked key)
PUT  /api/llm/configs/:id          — update a config
DELETE /api/llm/configs/:id        — delete a config
POST /api/llm/configs/:id/default  — set as default config
POST /api/llm/ping                 — test LLM connection before saving (returns supports_tool_calls, context_window)

POST /api/agents                        — create a new agent (returns agent with defaults pre-filled)
GET  /api/agents                        — list user's agents
GET  /api/agents/:id                    — get full agent config
PUT  /api/agents/:id                    — update agent config (any block)
DELETE /api/agents/:id                  — delete agent

POST /api/agents/:id/tools              — add a tool to an agent
PUT  /api/agents/:id/tools/:tool_id     — update a tool config
DELETE /api/agents/:id/tools/:tool_id   — remove a tool

POST /api/agents/:id/knowledge          — upload a file or add URL/text source
DELETE /api/agents/:id/knowledge/:source_id  — remove a knowledge source
GET  /api/agents/:id/knowledge          — list sources with indexing status

WS   /api/agents/:id/run                — launch agent session (streaming WebSocket, protocol below)
POST /api/agents/:id/run                — single-turn agent call (non-streaming)

GET  /api/traces                        — list user's traces (paginated, filterable by agent_id)
GET  /api/traces/:id                    — full trace detail
```

### WebSocket Message Protocol

The WebSocket at `WS /api/agents/:id/run` uses a typed JSON envelope for all messages.

**Client → Server**
```jsonc
// Send a message to the agent
{ "type": "message", "content": "what is 15% of the gold price?" }

// Abort the current in-flight run
{ "type": "abort" }
```

**Server → Client**
```jsonc
// Streaming text delta
{ "type": "delta", "content": "The current gold price is" }

// Tool call started
{ "type": "tool_start", "tool": "web_search", "input": { "query": "gold price USD" } }

// Tool call completed
{ "type": "tool_end", "tool": "web_search", "output_summary": "returned 3 results", "latency_ms": 312 }

// Agent reasoning step (shown in trace, not in chat)
{ "type": "reasoning", "step": 1, "text": "I need to look up the current gold price first..." }

// Response complete — includes full trace for this message
{ "type": "done", "trace_id": "abc123", "usage": { "input_tokens": 420, "output_tokens": 180, "total_tokens": 600 } }

// Error — recoverable (agent can continue)
{ "type": "error", "code": "tool_timeout", "message": "web_search timed out after 15s", "recoverable": true }

// Error — fatal (session must be relaunched)
{ "type": "error", "code": "budget_exceeded", "message": "Daily token budget reached", "recoverable": false }
```

### Agent Session Model

A session is the lifetime of one WebSocket connection. The server maintains conversation history in memory for the duration of the connection. When the connection closes, history is discarded — the next connection starts fresh. Long-term memory is persisted separately to `agent_memories` (see data model).

This keeps the server stateless between sessions — no session table needed. The client does not need to send history up; the server holds it for the connection lifetime.

### Error Response Schema (REST)

All REST errors return a consistent shape:
```jsonc
{
  "error": {
    "code": "validation_error",        // machine-readable
    "message": "model is required",    // human-readable
    "field": "model"                   // present on validation errors
  }
}
```

### Environment Variables

```bash
# Backend (.env)
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=...
SUPABASE_SERVICE_KEY=...      # server-side only, bypasses RLS for admin ops
SERVER_SECRET=...             # 32-byte random, used for AES key derivation
STORAGE_BUCKET=knowledge      # Supabase Storage bucket name for KB uploads

# Frontend (.env)
VITE_SUPABASE_URL=https://xxx.supabase.co
VITE_SUPABASE_ANON_KEY=...
VITE_API_BASE_URL=http://localhost:8000
```

---

## 10. Frontend Pages

| Route | Purpose |
|---|---|
| `/login` | Email/password form + "Continue with Google" button |
| `/onboarding` | First-run flow: step 1 — add an LLM config, step 2 — create first agent. Redirected here automatically after first sign-up |
| `/setup` | List of saved LLM configs + "Add new". Accessible from nav and from the LLM block in the agent builder |
| `/agents` | List of saved agents — name, LLM in use, last run. "New agent" button creates with defaults and redirects to `/agents/:id` |
| `/agents/:id` | Primary agent interface — split-panel builder + live chat (described in detail in Section 10a) |
| `/traces` | List of past agent runs, filterable by agent |
| `/traces/:id` | Step-by-step trace viewer — shows reasoning, tools called, results |

### First-run Flow
```
Sign up → email verified → redirect to /onboarding
  Step 1: Add LLM config (same form as /setup, inline)
    → Test connection → Save
  Step 2: "Your first agent is ready" — default agent pre-created with saved config
    → "Launch the Machine" → redirect to /agents/:id
```
Any subsequent login with an existing agent goes directly to `/agents` (or the last used agent).

---

## 10a. Agent Interface — Visual Design & Interaction Model

This is the centrepiece of the UI. It is a single full-screen page split into two panels: the **Agent Builder** on the left and the **Chat Console** on the right. Everything about the agent — its LLM, instructions, context, knowledge, memory, tools, and guardrails — is configured and visible on this one screen. No modals, no separate settings pages. The agent is a living thing you wire up and talk to in the same view.

---

### Panel Layout

```
┌──────────────────────────────────────────────────┬─────────────────────────┐
│                 AGENT BUILDER  (~60%)             │    CHAT CONSOLE (~40%)  │
│                                                   │                         │
│   [Instructions]   [Context]   [Knowledge Base]  │                         │
│          \              |             /           │   ┌─────────────────┐   │
│           \             |            /            │   │                 │   │
│            \            ↓           /             │   │  Configure your │   │
│  [LLM] ──→  [ ◈  A G E N T  ◈ ]   ←── [Memory]  │   │  agent and hit  │   │
│            /            ↑           \             │   │  Launch to      │   │
│           /             |            \            │   │  begin.         │   │
│   [Tool][Tool][Tool][Tool]       [Guardrails]     │   │                 │   │
│                                                   │   └─────────────────┘   │
│              [ ▶  Launch Agent ]                  │                         │
└──────────────────────────────────────────────────┴─────────────────────────┘
```

The divider between panels is **draggable** — the user can pull it left (more chat) or right (more builder) based on what they're focused on. The minimum width for either panel is 30% of the viewport.

---

### Agent Builder — Block Anatomy

Every block in the builder is a **node** connected to the central Agent node by an animated line. Each node is independently clickable to open an inline editor. None of them require navigating away.

#### Central Node — The Agent
- Displayed as a distinct, slightly larger node in the visual centre of the builder panel
- Shows the **agent's name** (user-defined, editable inline by clicking it)
- Pulses with a subtle glow when the agent is running
- All connection lines animate with a travelling-dot effect during active runs to show data flowing

#### LLM Block — comes from the left
- Shows: provider logo, model name, temperature, context window
- Clicking opens an inline panel: select from the user's saved LLM configs (dropdown) or go to `/setup` to add a new one
- No re-entering credentials here — configs are already saved and encrypted; the user just picks one
- During launch animation: slides in from the left edge with a brief ease-out, then the connecting line draws itself toward the agent node

#### Instructions Block — comes from the top-left (brain)
- The system prompt that defines the agent's role, personality, and behaviour
- Shows a truncated preview (first 2 lines) when collapsed
- Clicking opens an inline text editor with full markdown support
- Character count and a "reset to default" option shown at the bottom of the editor

#### Context Block — comes from the top-centre (brain)
- Static information injected into every agent run: user profile, current date, environment info, or any structured background the agent should always know
- Displayed as key-value pairs that the user can add, edit, or remove
- Think of it as the agent's "working memory at start" — things that don't change run to run but give the agent grounding

#### Knowledge Base Block — comes from the top-right
- Documents, files, or text snippets the agent can retrieve from on demand (RAG)
- Shows: number of documents indexed, last updated timestamp
- Clicking opens an inline panel: drag-and-drop file upload, paste text, or link a URL
- Files are chunked and embedded server-side; the agent searches them via a retrieval tool during runs
- A badge shows "Searching knowledge..." in the tool activity area when the agent retrieves from it

#### Memory Block — comes from the right
- **Short-term**: conversation history within the current session (automatic, always on)
- **Long-term**: facts the agent retains across sessions (e.g. user preferences, prior conclusions)
- Clicking shows a timeline view of stored long-term memories with the ability to delete individual entries
- Toggle to enable/disable long-term memory persistence per agent

#### Tools — come from the bottom
- Each plugged-in tool is its own node connected to the agent
- Tools can be toggled on/off by clicking a plug icon on each node — unplugged tools visually disconnect (line goes dashed, node dims)
- Clicking a tool node opens its config: name, description the agent sees, any required parameters or auth
- An "Add Tool" node sits at the end of the row, opening a tool picker
- During a run, the active tool being called highlights with a bright pulse

#### Guardrails Block — bottom-right corner
- Smaller, secondary node — important but not the focus
- Shows: max iterations, what happens when limit is hit (fail gracefully / return partial answer), any topic restrictions
- Clicking opens a compact inline editor for these settings

---

### Launch Flow — Sequence of Events

1. User finishes configuring blocks and clicks **▶ Launch**
2. The Launch button transitions to a spinner labelled "Starting..."
3. **Animation sequence** (staggered, ~800ms total):
   - LLM block slides in from the left, connecting line draws to agent node
   - Instructions and Context blocks drop in from the top, lines draw downward
   - Knowledge Base block slides in from top-right
   - Memory block slides in from the right
   - Tool nodes rise up from the bottom, one by one
   - Guardrails block fades in bottom-right
   - Agent node centre pulses once — agent is live
4. Chat Console on the right **activates**: the placeholder fades out, an input box appears at the bottom, and a subtle "Agent is ready" system message appears at the top of the chat thread
5. The Launch button changes to **■ Stop** for the duration of the session

---

### While the Agent is Running (Per Message)

- The connection line from the LLM block animates with a travelling pulse — showing the LLM is being called
- When a tool is invoked, its node in the builder highlights (bright ring) and a line pulses from the agent to that tool
- The chat panel shows a live **activity strip** above the input box: `Thinking... → Calling web_search → Calling calculator → Synthesising...`
- Each tool call in the activity strip is clickable and expands to show the tool input and raw output (mini trace inline)
- The agent node pulses continuously while any LLM call is in flight

---

### Editing Mid-Session

Any block can be edited while the agent is running. The behaviour depends on what is changed:

| What changed | Behaviour |
|---|---|
| Instructions | Banner in chat: "Instructions updated — applies from next message" |
| Context | Banner in chat: "Context updated — applies from next message" |
| LLM config | Banner in chat: "LLM updated — applies from next message" |
| Tool plugged in | Tool node animates in; applies immediately |
| Tool unplugged | Tool node dims and disconnects; agent will not call it in the next iteration |
| Knowledge Base updated | Badge shows "Re-indexing..." — new docs available after indexing completes |
| Memory cleared | Confirmation prompt before clearing; applies immediately |
| Guardrails | Applies from next message |

Changes never interrupt a message already in flight — they take effect at the next message boundary.

---

### Chat Console — Terminal Aesthetic

The chat console is styled like a developer terminal — dark, dense, monospace, no chat bubbles. It should feel like talking to a process, not a consumer app. The closest reference is the Claude Code CLI output style.

#### Visual Style
- **Background**: near-black (`#0a0a0a` or equivalent)
- **Font**: monospace throughout — `JetBrains Mono`, `Fira Code`, or system monospace fallback
- **No message bubbles** — flat, left-aligned text with clear role prefixes
- **Colour palette**: muted. Mostly off-white text on dark background. Colour used sparingly for meaning, not decoration

#### Message Format

```
  you  what is the capital of france?

agent  The capital of France is Paris.
```

- Role labels (`you`, `agent`) are short, lowercase, fixed-width, rendered in a muted colour
- A thin left border or colour shift distinguishes agent responses from user input
- No timestamps cluttering every line — timestamp shown on hover only, right-aligned in a muted tone

#### Streaming
- Agent response streams in character by character with a blinking block cursor (`█`) at the insertion point
- No "typing..." indicator — the cursor itself communicates that the agent is writing

#### Tool Call Output
When the agent invokes a tool, it appears inline in the thread as a collapsible block styled like terminal command output:

```
   tool  web_search("capital of france")
        ↳ [expand]  returned 3 results  · 240ms
```

- Collapsed by default — one line showing tool name, args, result summary, and latency
- Clicking `[expand]` opens the full raw input/output inline, indented, in a slightly dimmer colour
- Multiple tool calls stack vertically between the reasoning and the final response

#### Activity Strip (while running)
A single status line pinned just above the input box:

```
  ●  calling web_search...
```

- The dot pulses
- Text updates in real time: `Thinking...` → `Calling web_search...` → `Calling calculator...` → `Synthesising...`
- Disappears cleanly when the response is complete

#### Input Box
- Dark, borderless textarea flush with the console background
- Subtle placeholder: `message agent...`
- A `>` prefix to the left of the input, like a shell prompt
- `Enter` to send, `Shift+Enter` for newline
- When the agent is running, the input is disabled and the `>` dims — no double-sends

#### Inactive State
Before launch, the console shows a minimal centred message in muted monospace:

```
  agent not running
  configure blocks and hit Launch to begin
```

No illustration, no animation — just text.

#### Session Separator
When the user relaunches with a changed config, a separator is inserted inline:

```
  ── session started · fast-claude · gpt-4o · 14:32 ──
```

Muted, centred, single line. History above is preserved and readable.

#### Inline Trace
Each completed agent response has a `[trace]` link rendered inline at the end, in muted colour:

```
agent  The capital of France is Paris.   [trace ↗]
```

Clicking opens a right-side drawer (not a new page) showing the full step-by-step trace for that message — iterations, tool calls, token count, latency — in the same terminal monospace style.

#### Console Header
A minimal one-line bar at the top of the console panel:

```
  ◈ my-agent   gpt-4o   session 14:28        [clear]
```

- Agent name, LLM in use, session start time — all in muted monospace
- `[clear]` on the far right — manual only, requires a confirmation line printed in the console itself: `clear chat? [y/n]`

---

### Agent Naming

Every agent has a user-defined name displayed on the central node. On first visit the placeholder is `"Untitled Agent"` — clicking it opens an inline text input. The name is saved with the agent config and shown in the traces list so the user can identify which agent produced which run.

---

### Responsive / Narrow Viewport

On viewports narrower than 900px:
- The builder collapses into a bottom drawer triggered by a **"Configure"** button
- The chat takes the full screen
- The drawer slides up over the chat with the node graph shown in a compact scrollable list view (not the visual graph) for editing
- Launch button lives in the drawer footer

---

### UX Decisions

| Decision | Choice |
|---|---|
| Panel split | Draggable divider, 60/40 default, 30% minimum per panel |
| Edit during run | Allowed, applied at next message boundary with banner notification |
| Relaunch behaviour | Chat preserved with session separator inserted |
| Chat reset | Manual only — explicit "Clear chat" button in the console header |
| Tool on/off | Toggle per tool without leaving the builder view |
| Trace access | Inline expand per message + full detail at `/traces/:id` |
| Mobile | Builder collapses to bottom drawer, chat goes full screen |

---

## 10b. Agent Building Block Configuration

Every block in the agent builder is fully configurable via its inline editor. This section defines the complete set of settings available for each block — what can be tuned, what it does, and what the defaults are.

---

### Instructions

The system prompt that defines who the agent is and how it behaves.

| Setting | Type | Default | Description |
|---|---|---|---|
| `system_prompt` | long text (markdown) | `""` | The full system prompt. Supports markdown. Injected at the top of every LLM call. |
| `persona_name` | text | `""` | Optional name the agent refers to itself as (e.g. "Aria"). If blank, agent does not self-identify by name. |
| `response_style` | enum | `balanced` | `concise` / `balanced` / `verbose` — appended as a style instruction to the system prompt |
| `output_format` | enum | `markdown` | `markdown` / `plain_text` / `json` — how the agent formats its responses |
| `response_language` | text | `en` | BCP 47 language code. Agent responds in this language regardless of input language. |
| `show_reasoning` | bool | `false` | If true, agent prefixes responses with a brief chain-of-thought before the final answer |
| `reset_to_default` | action | — | Clears back to the default system prompt template for a general-purpose assistant |

---

### Context

Static key-value data injected into every agent run. Gives the agent grounding without burning tokens on retrieval.

| Setting | Type | Default | Description |
|---|---|---|---|
| `entries` | list of `{key, value}` | `[]` | User-defined key-value pairs. Injected as a structured block at the top of the context. E.g. `user_name: Sam`, `timezone: America/New_York` |
| `auto_inject_datetime` | bool | `true` | Automatically injects current date and time at run start |
| `auto_inject_user_profile` | bool | `true` | Injects the authenticated user's name and email from their account |
| `render_as` | enum | `yaml` | `yaml` / `json` / `prose` — how the context block is formatted before injection into the prompt |

---

### Knowledge Base

Documents and text the agent can retrieve from on demand during a run (RAG).

| Setting | Type | Default | Description |
|---|---|---|---|
| `sources` | list of files / URLs / text pastes | `[]` | The documents indexed for this agent. Each source shows name, size, last indexed timestamp. |
| `chunk_size` | int (tokens) | `512` | How large each indexed chunk is. Smaller = more precise retrieval, larger = more context per chunk. |
| `chunk_overlap` | int (tokens) | `64` | Token overlap between adjacent chunks to avoid splitting mid-thought. |
| `top_k` | int | `4` | Number of chunks retrieved per query. Higher = more context, more tokens consumed. |
| `similarity_threshold` | float 0–1 | `0.7` | Minimum similarity score for a chunk to be returned. Filters out weak matches. |
| `reranking` | bool | `false` | Run a reranker pass over retrieved chunks before injecting — more accurate, adds latency. |
| `show_sources` | bool | `true` | If true, agent appends source citations to answers that drew from the knowledge base. |
| `auto_refresh_urls` | bool | `false` | Re-index URL sources on a daily schedule to pick up content changes. |
| `embedding_model` | enum | `text-embedding-3-small` | The model used to embed documents and queries. Changing this triggers a full re-index. |

---

### Memory

What the agent remembers within and across sessions.

#### Short-term (conversation history)

| Setting | Type | Default | Description |
|---|---|---|---|
| `history_window` | int (messages) | `20` | How many past messages to include in each LLM call. Higher = more context, more tokens. |
| `summarise_old_messages` | bool | `false` | When history exceeds the window, compress older messages into a summary rather than dropping them. |

#### Long-term (persisted across sessions)

| Setting | Type | Default | Description |
|---|---|---|---|
| `long_term_enabled` | bool | `false` | Enable storing facts across sessions. When on, agent can read and write persistent memories. |
| `memory_types` | multi-select | `[preferences, facts]` | What categories to store: `preferences`, `facts`, `decisions`, `corrections` |
| `max_memories` | int | `100` | Cap on number of stored long-term memories for this agent. Oldest are evicted when exceeded. |
| `retention_days` | int | `90` | How long individual memories persist before expiring. `0` = forever. |
| `auto_compress` | bool | `true` | Periodically merge similar memories to reduce redundancy. |
| `memory_visibility` | enum | `agent_only` | `agent_only` / `visible_in_chat` — whether the user sees memory reads/writes in the chat thread |

---

### Tools

Each tool is its own configurable node. Settings apply per tool.

#### Per-Tool Settings

| Setting | Type | Default | Description |
|---|---|---|---|
| `enabled` | bool | `true` | Whether this tool is available to the agent. Toggling off disconnects the node without deleting it. |
| `name` | text | tool default | The function name the agent uses when calling this tool. Must be unique across tools for this agent. |
| `description` | long text | tool default | What the agent reads to decide when to use this tool. Good descriptions are the single biggest lever on tool usage quality. |
| `parameters` | JSON schema | tool default | The input schema the agent must conform to when calling the tool. Editable for custom tools. |
| `auth` | key-value credentials | `{}` | API keys, tokens, or other credentials required by the tool. Encrypted at rest, same as LLM keys. |
| `timeout_seconds` | int | `15` | Abort the tool call if it takes longer than this. |
| `max_calls_per_run` | int | `5` | Maximum times this tool can be called in a single agent run. Prevents runaway loops on one tool. |
| `retry_on_failure` | bool | `true` | Retry once on transient errors (timeout, 5xx) before marking the tool call as failed. |
| `show_result_in_chat` | bool | `true` | Whether the tool's raw result is shown (collapsed) in the chat console. |
| `result_truncation_chars` | int | `2000` | Truncate tool output before injecting into the LLM context if it exceeds this length. |

#### Tool Picker (Add Tool)
When the user clicks "Add Tool", they see:
- **Built-in tools**: pre-configured, zero-auth (e.g. `calculator`, `current_datetime`)
- **API tools**: pre-built integrations requiring auth (e.g. `web_search`, `code_interpreter`, `weather`)
- **Custom tool**: user defines name, description, parameter schema, and an HTTP endpoint the platform calls

---

### Guardrails

Behavioural constraints and safety rails on the agent's execution.

| Setting | Type | Default | Description |
|---|---|---|---|
| `max_iterations` | int | `5` | Hard cap on ReAct loop iterations per message. Prevents infinite reasoning loops. |
| `on_max_iterations` | enum | `return_partial` | What to do when the cap is hit: `return_partial` (return what the agent has so far) / `fail_with_message` (tell the user the agent couldn't complete) / `ask_user` (pause and ask for guidance) |
| `max_tool_calls_per_run` | int | `20` | Total tool calls allowed across all tools in a single agent run. |
| `max_tokens_per_run` | int | `8000` | Token budget for the entire agent run (input + output across all LLM calls). Prevents runaway cost on complex queries. |
| `topic_restrictions` | list of text | `[]` | Topics the agent should refuse to engage with. Injected as guardrail instructions. E.g. `"competitor products"`, `"medical advice"`. |
| `allow_clarifying_questions` | bool | `true` | If true, agent can ask the user a follow-up question when the input is ambiguous rather than guessing. |
| `pii_detection` | bool | `false` | Scan agent outputs for PII (names, emails, phone numbers, SSNs) and mask before displaying. |
| `safe_tool_mode` | bool | `false` | Validate tool outputs against expected schema before injecting into the LLM context. Slower but prevents prompt injection via malicious tool responses. |
| `confidence_threshold` | float 0–1 | `0.0` | If the agent's self-assessed confidence is below this, it appends a disclaimer. `0.0` = always respond, `0.8` = only respond when confident. |

---

### Output / Response Format

How the agent structures and delivers its final response.

| Setting | Type | Default | Description |
|---|---|---|---|
| `format` | enum | `markdown` | `markdown` / `plain_text` / `json` / `custom_schema` — the format of the agent's final response |
| `json_schema` | JSON schema | `null` | When `format = json`, the agent is constrained to output valid JSON matching this schema. Used for programmatic consumption. |
| `verbosity` | enum | `balanced` | `minimal` (shortest possible answer) / `balanced` / `detailed` (full explanation with examples) |
| `include_citations` | bool | `true` | When the agent draws from knowledge base or tools, append source references at the end of the response. |
| `strip_thinking` | bool | `true` | If the model outputs chain-of-thought tokens, strip them before displaying to the user. |
| `response_length_limit` | int (chars) | `null` | Hard truncate the response at this length. `null` = no limit. |

---

## 11. Security Summary

| Concern | Mitigation |
|---|---|
| API keys at rest | AES-256-GCM encryption, unique key per user |
| API keys in transit | HTTPS only |
| Unauthorised DB access | Supabase RLS — enforced at Postgres level |
| XSS token theft | JWT in httpOnly cookie, not localStorage |
| CSRF | SameSite cookie policy + CSRF token on mutations |
| Runaway agent | Max iteration cap, per-request token budget |

---

## 12. What This Showcases

| Skill | Where it shows |
|---|---|
| Security engineering | Envelope encryption, RLS, httpOnly JWTs, masked key display |
| Reliability thinking | Fallback provider, retry logic, timeout config, daily budget |
| Agent architecture | Multi-step ReAct loop, trace system, tool abstraction |
| Provider abstraction | LiteLLM across 7 providers behind one clean interface |
| Full-stack | React + FastAPI + Postgres, all wired together |
| API design | Clean REST + WebSocket contract |
| Observability | Structured traces, token counts, latency, provider used |

---

## 13. v1 Scope vs. Future Roadmap

### v1 — Build This

| Area | What's included |
|---|---|
| Auth | Email/password + Google SSO, httpOnly JWT cookies |
| LLM config | All 7 providers + Custom (OpenAI-compatible), multiple named configs, default designation, model dropdown/freetext, temperature, max_tokens, timeout, retries, fallback by config reference, daily budget per config |
| Ping / test | Test primary + fallback before saving; auto-detect tool calling support + context window; warn if tool calling unsupported |
| Agent | Multi-step ReAct loop, max 5 iterations, tool execution |
| Agent interface | Split-panel builder + chat, animated node graph, inline editing of all blocks, launch flow, mid-session config updates, session separators |
| Agent blocks | LLM, Instructions, Context, Knowledge Base (RAG), Memory (short + long term), Tools, Guardrails |
| Tools | calculator, current_datetime, url_reader, wikipedia_search (zero-auth) + web_search via Tavily |
| Knowledge Base | pgvector via Supabase, file/URL/text sources, chunking + embedding pipeline, cosine similarity retrieval |
| Data model | agents, agent_tools, agent_traces, knowledge_sources, knowledge_chunks — full RLS on all tables |
| Traces | Full trace stored per run, linked to agent, inline expand in chat + full detail at /traces/:id |
| Chat | Streaming WebSocket chat with live activity strip showing tool calls |
| Security | AES-256-GCM encryption + RLS on all tables |

### Future Roadmap

| Area | What's planned |
|---|---|
| LLM config | Custom system prompt, RPM/TPM throttling, exact-match caching |
| Observability | LangSmith / Helicone integration |
| Tools | Code interpreter, image generation, send email, database query, user-defined custom HTTP tools |
| Agent | Sub-agent delegation, parallel reasoning branches |
| Config UX | Per-session LLM config override |
| Knowledge Base | Reranking, auto-refresh URLs, alternative embedding providers |
| Team / org | Shared agents and configs within a workspace |

---

## 14. Deployment Target

**v1 deployment: Railway**

| Concern | Decision |
|---|---|
| Backend | FastAPI container on Railway — single service, supports long-lived WebSocket connections |
| Frontend | Vercel — static React build, zero config |
| Database | Supabase (managed) — no self-hosted Postgres needed |
| File storage | Supabase Storage — built in, no separate S3 setup |
| Background tasks | FastAPI `BackgroundTasks` — sufficient for v1 KB indexing. No separate worker process needed. |
| Environment secrets | Railway environment variables (backend), Vercel environment variables (frontend) |

Railway was chosen over Render/Fly because it supports persistent WebSocket connections without extra config and has a simple Docker-based deploy.

---

## 15. Development Cycles

Each cycle is a shippable, committable increment. Nothing is left half-built at the end of a cycle.

---

### Cycle 1 — Foundation
**Goal**: repo starts, both servers run, CI passes, GitHub tooling is fully configured. Nothing functional yet but the skeleton is production-grade from day one.

#### Monorepo structure
```
the-machine/
  backend/                    ← FastAPI app
  frontend/                   ← React + Vite app
  supabase/
    migrations/
      001_initial_schema.sql  ← all tables, RLS, pgvector in one file
  .github/                    ← full GitHub tooling (see below)
  docker-compose.yml          ← local Postgres + pgvector for integration tests
  .env.example                ← documents every required env var, safe to commit
  README.md                   ← punchy, problem-first (see below)
```

#### Backend scaffold
- `pyproject.toml` — dependencies, ruff + mypy config
- FastAPI app with `GET /health` → `{ status: "ok" }`
- `.env` structure: `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_KEY`, `SERVER_SECRET`, `STORAGE_BUCKET`

#### Frontend scaffold
- Vite + React + TypeScript
- Tailwind CSS + shadcn/ui init
- React Router v6 setup with placeholder routes for all pages
- `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`, `VITE_API_BASE_URL` in `.env`

#### Supabase
- All tables created via `supabase/migrations/001_initial_schema.sql`:
  `llm_configs`, `agents`, `agent_tools`, `agent_traces`, `knowledge_sources`, `knowledge_chunks`, `agent_memories`
- pgvector extension enabled
- RLS policies on all tables
- Unique partial index on `llm_configs` for `is_default`

#### README

**Opener**: `Think. Act. Observe. That's The Machine.`

The opener is the ReAct loop (Reason → Act → Observe) doubled as the product name. A developer who knows agent architecture gets it immediately. One who doesn't will get it the moment they use it.

**Structure** (first page only — everything else goes to `/docs`):

```
Think. Act. Observe. That's The Machine.

A multi-provider AI agent platform. Bring your own LLM.
The reasoning, the security, and the traces are on us.

---

Flowise, Langflow, and Dify wire LangChain components together.
LangGraph gives you a loop to write yourself.
LangSmith observes it — for a fee, separately.

The Machine is none of these.

Bring your credentials for any of 8 providers — encrypted per-user with
AES-256-GCM, never stored in plaintext. A purpose-built ReAct loop runs
against them. Every reasoning step, tool call, and decision is stored as
a first-class trace in your own database.

No LangChain. No external observability service. No vendor picking your model.

---

• Any LLM        — OpenAI · Claude · Gemini · Grok · Bedrock · Azure · Ollama · Custom
• Real reasoning — multi-step ReAct loop, not a single prompt
• Full traces    — every step, tool call, and token. First-party. Your DB.
• Your keys      — AES-256-GCM encrypted, per-user, never returned to the client
• Built-in tools — web search, calculator, URL reader, Wikipedia, and more
• Knowledge base — upload docs, the agent retrieves from them on demand

[quick architecture — ASCII, ~8 lines]

---

Quick start:

git clone ...
cp .env.example .env        # add your Supabase + LLM provider keys
docker-compose up           # local Postgres + pgvector
cd backend && uvicorn app.main:app --reload
cd frontend && npm run dev
open http://localhost:5173

---

Full docs → /docs   API reference → /docs/api   Contributing → CONTRIBUTING.md
```

#### `.github` folder

```
.github/
  copilot-instructions.md          ← repo-wide Copilot context
  copilot/
    coding-agent.md                ← Copilot coding agent rules
  actions/
    setup-backend/
      action.yml                   ← composite: Python + pip install + cache
    setup-frontend/
      action.yml                   ← composite: Node + npm install + cache
  workflows/
    ci.yml                         ← lint + types + tests on every PR
    deploy.yml                     ← deploy to Railway + Vercel on push to main
    ai-review.yml                  ← AI agent that reviews every PR
  ISSUE_TEMPLATE/
    bug_report.yml
    feature_request.yml
  PULL_REQUEST_TEMPLATE.md
  CODEOWNERS
  dependabot.yml
  scripts/
    seed_db.py
    reset_db.sh
```

---

**`copilot-instructions.md`**

Repo-wide context loaded by GitHub Copilot on every suggestion. Covers:
- Stack: FastAPI (async Python) + React + TypeScript + Supabase Postgres + pgvector
- Key conventions: `async`/`await` throughout the backend, OpenAI function-calling format as the canonical tool input shape, AES-256-GCM for all secrets via the encryption layer
- Where things live: agent loop → `backend/app/agent/`, provider adapter → `backend/app/llm/`, DB access → `asyncpg` only, frontend state → React Context + hooks
- Hard rules Copilot must follow:
  - Never suggest LiteLLM
  - Never use `localStorage` for tokens — httpOnly cookies only
  - Never write raw SQL strings — use parameterised queries via asyncpg
  - Never store a secret in plaintext — all sensitive values go through `backend/app/core/encryption.py`
  - Tool results always injected back via the provider adapter, never by building raw message strings

---

**`copilot/coding-agent.md`**

Configures the GitHub Copilot coding agent (used in Copilot Workspace and `@github` agent in Copilot Chat). More prescriptive than `copilot-instructions.md` — tells the agent what it owns and what to leave alone:

```markdown
# Copilot Coding Agent — The Machine

## You can freely edit
- backend/app/agent/      — ReAct loop logic
- backend/app/tools/      — tool implementations
- frontend/src/components — UI components
- tests/                  — any test file

## Be careful with
- backend/app/llm/        — provider adapter; format conversions are intentional, don't "simplify"
- backend/app/core/encryption.py — do not change the key derivation scheme
- supabase/migrations/    — never edit existing migrations; always add a new numbered file

## Never touch
- .env files
- CODEOWNERS
- The AES-GCM nonce generation logic

## Code style
- Python: ruff-formatted, type hints on all function signatures
- TypeScript: strict mode, no `any`
- Commit messages: conventional commits (feat/fix/chore/docs/test)
```

---

**`actions/setup-backend/action.yml`** — composite action, used in both `ci.yml` and `deploy.yml`:
```yaml
name: Setup Python backend
runs:
  using: composite
  steps:
    - uses: actions/setup-python@v5
      with: { python-version: '3.12' }
    - uses: actions/cache@v4
      with:
        path: ~/.cache/pip
        key: pip-${{ hashFiles('backend/pyproject.toml') }}
    - run: pip install -e ".[dev]"
      shell: bash
      working-directory: backend
```

**`actions/setup-frontend/action.yml`** — same pattern for Node:
```yaml
name: Setup Node frontend
runs:
  using: composite
  steps:
    - uses: actions/setup-node@v4
      with: { node-version: '20', cache: 'npm', cache-dependency-path: frontend/package-lock.json }
    - run: npm ci
      shell: bash
      working-directory: frontend
```

---

**`workflows/ci.yml`** — every PR:
```
backend job:
  → setup-backend (composite action)
  → ruff check backend/
  → mypy backend/
  → pytest backend/tests/unit/ -x

frontend job:
  → setup-frontend (composite action)
  → eslint frontend/src/
  → tsc --noEmit
  → vitest run
```

---

**`workflows/deploy.yml`** — push to `main`:
```
deploy-backend:
  → setup-backend
  → docker build backend/ → push to Railway registry
  → railway deploy

deploy-frontend:
  → setup-frontend
  → npm run build
  → vercel deploy --prod
```

---

**`workflows/ai-review.yml`** — the agent showcase

Triggers on every PR open or update. Uses the **GitHub Models API** (accessed via `GITHUB_TOKEN` — no external API key, free) to post a structured AI code review as a PR comment.

```
Trigger: pull_request (opened, synchronize)

Steps:
  1. Checkout repo + fetch diff (git diff origin/main...HEAD)
  2. Read .github/copilot-instructions.md as project context
  3. Call GitHub Models API (gpt-4o via github.com/models)
     Prompt:
       "You are a senior engineer reviewing a PR for The Machine, an AI agent platform.
        Project conventions: [copilot-instructions.md contents]
        PR diff: [diff]
        Review for: correctness, security, convention violations, missing tests.
        Format your response as:
          ## Summary
          ## Concerns (if any)
          ## Suggestions (if any)
          ## Verdict: ✅ Looks good / ⚠️ Minor issues / 🚫 Needs changes"
  4. Post response as a PR comment via GitHub API
  5. If verdict = 🚫, request changes; otherwise approve
```

This is intentionally meta — an AI agent platform with an AI agent guarding its own codebase. The GitHub Models API makes it zero-cost and zero-secret-management.

---

**`PULL_REQUEST_TEMPLATE.md`**:
```markdown
## What changed

## Why

## How to test

## Checklist
- [ ] Tests added or updated
- [ ] No secrets committed
- [ ] Types pass (`mypy` / `tsc --noEmit`)
- [ ] Conventional commit message (`feat` / `fix` / `chore` / `docs` / `test`)
```

---

**`dependabot.yml`** — weekly PRs for pip + npm:
```yaml
version: 2
updates:
  - package-ecosystem: pip
    directory: /backend
    schedule: { interval: weekly }
    labels: [dependencies, backend]
  - package-ecosystem: npm
    directory: /frontend
    schedule: { interval: weekly }
    labels: [dependencies, frontend]
```

---

**`CODEOWNERS`**:
```
*                        @your-github-handle
/backend/app/llm/        @your-github-handle   # provider adapter — format conversions are intentional
/backend/app/core/       @your-github-handle   # encryption layer — do not simplify
/supabase/               @your-github-handle   # schema changes require review
/.github/                @your-github-handle   # CI/CD changes require review
```

---

**`ISSUE_TEMPLATE/bug_report.yml`** — structured fields: description, steps to reproduce, expected vs actual, LLM provider + model at time of issue, browser/OS.

**`ISSUE_TEMPLATE/feature_request.yml`** — structured fields: problem statement, proposed solution, which agent block it affects, alternatives considered.

---

**`scripts/seed_db.py`** — inserts a test user, a default LLM config (OpenAI, points to `OPENAI_API_KEY` from env), and a default agent pre-loaded with all 5 built-in tools. Run once after `reset_db.sh` to get a working local environment without clicking through onboarding.

**`scripts/reset_db.sh`** — drops all tables and re-applies `supabase/migrations/001_initial_schema.sql` against the local Docker Postgres instance.

**Commit**: `scaffold: monorepo, FastAPI + React skeletons, Supabase schema, full .github tooling, README`

---

### Cycle 2 — Auth
**Goal**: a user can sign up, log in with email or Google, and all API calls are protected.

- Supabase Auth wired to FastAPI — JWT middleware validates every request
- `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`
- httpOnly cookie set on login, cleared on logout
- Login page (`/login`) — email/password form + Google SSO button
- Onboarding page (`/onboarding`) — first-run redirect after sign-up (shell only, wired in Cycle 3)
- Protected route wrapper in React — unauthenticated users redirected to `/login`
- Token refresh handled client-side via Supabase JS SDK

**Commit**: `feat(auth): email+password login, Google SSO, JWT middleware, protected routes`

---

### Cycle 3 — LLM Config
**Goal**: a user can configure, test, and save any of the 8 LLM providers.

- Encryption layer: `AES-256-GCM` with per-user derived key (`HMAC-SHA256(SERVER_SECRET, user_id)`)
- LLM config CRUD API — all 6 endpoints
- Ping endpoint — sends test completion, checks tool calling support + context window, returns structured result
- `/setup` page — provider picker, credential form, model dropdown (known models + freetext), Test Connection, Save, set default
- Onboarding step 1 wired: first-run user lands on `/onboarding`, completes LLM config inline
- Masked key display after saving

**Commit**: `feat(llm-config): encryption, CRUD, ping endpoint, setup page`

---

### Cycle 4 — Agent CRUD
**Goal**: a user can create, configure, and save a named agent with all blocks.

- Agent + agent_tools CRUD API (all endpoints)
- `/agents` list page — cards showing agent name, LLM, last run, "New agent" button
- `/agents/:id` — static agent builder (no animation yet): all blocks rendered, inline editors for every field in every block
- Onboarding step 2 wired: default agent auto-created after LLM config saved, redirect to `/agents/:id`
- Tool picker: built-in tools listed, toggled on/off, tool config editor

**Commit**: `feat(agent-crud): agent + tools API, agents list, static agent builder UI`

---

### Cycle 5 — Agent Runtime
**Goal**: a user can launch an agent, send a message, and get a streaming response with real tool use.

- Frontend tests: `AuthContext` (syncCookie called on getSession + onAuthStateChange), `ProtectedRoute` (401 redirect loop regression), `AgentsPage` (401 → navigate without remount loop)
- ReAct loop: Reason → Act (parallel tool calls) → Observe → Respond, max iterations enforced
- Tool result injection: canonical internal format, each provider adapter converts back to its own message format
- All 5 default tools implemented: `calculator`, `current_datetime`, `url_reader`, `wikipedia_search`, `web_search`
- WebSocket endpoint `WS /api/agents/:id/run` — full typed message protocol
- Trace capture: every run produces a `agent_traces` row with full iteration JSON
- Terminal chat console wired up: streaming deltas, tool_start/tool_end events, activity strip, `[trace]` link per message
- Launch / Stop button flow (no animation yet — that's Cycle 7)
- Guardrails enforced: max iterations, max tokens per run, daily budget check

**Commit**: `feat(agent-runtime): ReAct loop, 5 default tools, WebSocket streaming, trace capture, terminal chat`

---

### Cycle 6 — Knowledge Base
**Goal**: a user can upload documents and the agent can search them.

- `agent_memories` table added to schema
- File upload → Supabase Storage → `knowledge_sources` row with status `pending`
- Async indexing pipeline (FastAPI `BackgroundTasks`): extract text → chunk → embed → store vectors
- `knowledge_search` tool wired into the agent
- `save_memory` tool wired into the agent (when `long_term_enabled = true`)
- KB block UI: drag-and-drop upload, source list with indexing status badges, remove source
- Memory block UI: long-term toggle, stored memories list with delete

**Commit**: `feat(knowledge-base): file upload, async indexing, pgvector retrieval, memory tools`

---

### Cycle 7 — Polish + Animation
**Goal**: the product looks and feels finished. This is what gets demoed and shared.

- Agent builder launch animation sequence (staggered block fly-in, travelling-dot connections)
- Live node graph activity during runs (tool nodes pulse, LLM line animates)
- Mid-session edit banners in chat
- Draggable panel divider
- `/traces` list page + full detail drawer (inline in chat and standalone)
- Error states: LLM failure, tool timeout, budget exceeded — all surfaced correctly in chat
- Loading states on all async operations
- Empty states: no agents, no tools, no knowledge sources
- Mobile responsive (builder collapses to bottom drawer)
- First-run onboarding polish

**Commit**: `feat(polish): animations, traces UI, error/loading/empty states, mobile layout`

---

*Last updated: 2026-04-04 — gap analysis resolved, deployment target set (Railway), development cycles defined*
