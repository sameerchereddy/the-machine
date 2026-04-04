from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    supabase_url: str
    supabase_anon_key: str
    supabase_service_key: str
    server_secret: str
    storage_bucket: str = "knowledge"
    database_url: str | None = None  # postgres://... required for migrations + direct DB access

    # CORS — tighten in production
    allowed_origins: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    @field_validator("server_secret")
    @classmethod
    def server_secret_min_length(cls, v: str) -> str:
        if len(v) < 32:
            raise ValueError("SERVER_SECRET must be at least 32 characters")
        return v


try:
    settings: Settings = Settings()  # type: ignore[call-arg]
except Exception:  # noqa: BLE001
    settings = None  # type: ignore[assignment]
