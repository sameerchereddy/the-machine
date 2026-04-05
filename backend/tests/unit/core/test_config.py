"""
Smoke tests for app config — verifies Settings loads from env
and rejects obviously invalid values.
"""

import pytest
from pydantic import ValidationError


class TestSettings:
    def test_loads_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
        monkeypatch.setenv("SERVER_SECRET", "a" * 64)

        # Re-import to pick up patched env
        import importlib

        import app.core.config as config_module

        importlib.reload(config_module)

        s = config_module.Settings()  # type: ignore[call-arg]
        assert s.supabase_url == "https://test.supabase.co"

    def test_server_secret_too_short_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
        monkeypatch.setenv("SERVER_SECRET", "tooshort")

        import importlib

        import app.core.config as config_module

        importlib.reload(config_module)

        with pytest.raises((ValidationError, ValueError)):
            config_module.Settings()  # type: ignore[call-arg]
