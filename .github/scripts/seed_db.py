#!/usr/bin/env python3
"""
Seed the local dev database with a test user, one LLM config, and one agent.
Requires DATABASE_URL in env (or .env file at repo root).

Usage:
    python .github/scripts/seed_db.py
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

# Allow running from repo root without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

import asyncpg
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")

DATABASE_URL = os.environ.get("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set. Add it to .env or export it.")
    sys.exit(1)

TEST_USER_ID = "00000000-0000-0000-0000-000000000001"
LLM_CONFIG_ID = str(uuid.uuid4())
AGENT_ID = str(uuid.uuid4())


async def seed() -> None:
    conn = await asyncpg.connect(DATABASE_URL)
    try:
        # Seed LLM config (plaintext key — local dev only, never commit real keys)
        await conn.execute(
            """
            INSERT INTO llm_configs (id, user_id, provider, label, model, encrypted_api_key, is_default)
            VALUES ($1, $2, 'openai', 'Dev OpenAI', 'gpt-4o-mini', 'dev-placeholder-key', true)
            ON CONFLICT (id) DO NOTHING
            """,
            LLM_CONFIG_ID,
            TEST_USER_ID,
        )

        # Seed agent
        await conn.execute(
            """
            INSERT INTO agents (id, user_id, name, description, llm_config_id, system_prompt)
            VALUES ($1, $2, 'Dev Agent', 'Seed agent for local development', $3, 'You are a helpful assistant.')
            ON CONFLICT (id) DO NOTHING
            """,
            AGENT_ID,
            TEST_USER_ID,
            LLM_CONFIG_ID,
        )

        print(f"Seeded LLM config: {LLM_CONFIG_ID}")
        print(f"Seeded agent:      {AGENT_ID}")
        print("Done.")
    finally:
        await conn.close()


asyncio.run(seed())
