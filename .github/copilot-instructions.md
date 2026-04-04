# GitHub Copilot Instructions — The Machine

## What this project is
A multi-provider AI agent platform. Users bring their own LLM credentials, and a custom ReAct loop runs against them with full trace visibility. No LangChain. No LiteLLM. No external observability service.

## Stack
- **Backend**: FastAPI (Python 3.12, fully async), Supabase Postgres + pgvector, asyncpg
- **Frontend**: React 18 + TypeScript + Vite + Tailwind CSS + shadcn/ui
- **Auth**: Supabase Auth, JWT stored in httpOnly cookies
- **LLM routing**: Custom provider adapter in `backend/app/llm/` — one BaseProvider per SDK
- **Encryption**: AES-256-GCM, per-user envelope encryption in `backend/app/core/encryption.py`

## Where things live
```
backend/app/
  main.py           — FastAPI app entry point, CORS, routers registered here
  core/
    config.py       — pydantic-settings, all env vars
    security.py     — Supabase admin client, verify_token()
    deps.py         — get_current_user dependency, CurrentUser type alias
    encryption.py   — AES-256-GCM encrypt/decrypt (add in Cycle 3)
  api/
    auth.py         — POST /api/auth/login, /logout, GET /me
  llm/
    adapter.py      — BaseProvider, ProviderWithRetry, build_adapter factory
    types.py        — LLMResponse, StreamChunk, ToolCall, Usage
    providers/      — one file per provider SDK
  agent/            — ReAct loop (add in Cycle 5)
  tools/            — tool implementations (add in Cycle 5)

frontend/src/
  pages/            — one file per route
  components/       — reusable UI components
  context/
    AuthContext.tsx — AuthProvider, useAuth hook
  lib/
    supabase.ts     — Supabase client singleton
    utils.ts        — cn() helper for Tailwind class merging
```

## Non-negotiable conventions

### Backend
- **async/await everywhere** — no synchronous DB calls or blocking I/O
- **All DB access via asyncpg** — no ORMs, no raw string queries (use parameterised `$1, $2` placeholders)
- **All secrets through the encryption layer** — never store a credential in plaintext in the DB
- **Tool calling always uses OpenAI function format as input** — provider adapters convert internally
- **Type hints on every function signature** — mypy strict mode must pass

### Frontend
- **No `localStorage` for tokens** — Supabase Auth uses httpOnly cookies via the backend
- **`cn()` from `@/lib/utils` for all Tailwind class composition** — never string concatenation
- **TypeScript strict mode** — no `any`, no `@ts-ignore`

### Both
- **Never suggest LiteLLM** — we have a custom provider adapter
- **Never suggest LangChain** — the ReAct loop is custom
- **Conventional commit messages** — `feat:`, `fix:`, `chore:`, `docs:`, `test:`

## Security rules
- API keys, secrets, and credentials → `backend/app/core/encryption.py` before touching the DB
- JWTs → httpOnly cookies only, never `localStorage` or response body
- DB queries → asyncpg parameterised queries only, never f-strings with user input
- The `config_enc` / `credentials_enc` columns in the DB → always encrypted, never read and returned to the client as plaintext
