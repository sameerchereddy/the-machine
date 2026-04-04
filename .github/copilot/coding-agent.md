# Copilot Coding Agent — The Machine

This file configures the GitHub Copilot coding agent for use in Copilot Workspace and `@github` mentions in Copilot Chat.

## You can freely edit
- `backend/app/agent/` — ReAct loop logic, iteration control
- `backend/app/tools/` — tool implementations (calculator, web_search, etc.)
- `backend/app/routers/` — API route handlers
- `frontend/src/pages/` — page components
- `frontend/src/components/` — UI components
- `tests/` — any test file in any directory

## Edit carefully — these have intentional design decisions
- `backend/app/llm/` — provider adapter. Format conversions between OpenAI/Anthropic/Gemini/Bedrock are intentional. Do not "simplify" or unify them — each provider has its own required format.
- `backend/app/core/config.py` — adding new env vars is fine; do not change the Settings class base or model_config.
- `supabase/migrations/` — **never edit existing migration files**. Always add a new numbered file (e.g. `002_add_column.sql`). Editing existing migrations breaks anyone who has already run them.

## Never touch
- `.env` files of any kind
- `backend/app/core/encryption.py` — do not change the key derivation scheme (`HMAC-SHA256(SERVER_SECRET, user_id)`) or the AES-GCM nonce generation. Changing these will silently corrupt all existing encrypted credentials.
- `CODEOWNERS`
- `.github/workflows/` — CI/CD changes require explicit review

## Code style
- **Python**: ruff-formatted (line length 100), type hints on all signatures, async functions for all I/O
- **TypeScript**: strict mode, no `any`, no non-null assertions without a comment explaining why
- **Commit messages**: conventional commits — `feat(scope):`, `fix(scope):`, `chore:`, `docs:`, `test:`
- **No co-author attribution lines** in commit messages

## What this project is NOT
- It is not a LangChain project — do not suggest LangChain imports
- It is not using LiteLLM — do not suggest LiteLLM
- It is not a visual workflow builder — the agent loop is custom Python, not a graph of nodes
