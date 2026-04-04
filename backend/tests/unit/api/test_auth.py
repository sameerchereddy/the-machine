"""
Unit tests for auth endpoints.
Supabase is fully mocked — no real network calls.
"""
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app, raise_server_exceptions=False)


def _mock_user(uid: str = "user-123", email: str = "test@example.com") -> dict[str, str]:
    return {"id": uid, "email": email}


class TestLogin:
    def test_email_password_sets_cookie(self) -> None:
        mock_result = MagicMock()
        mock_result.session.access_token = "tok-abc"
        mock_result.user.id = "user-123"
        mock_result.user.email = "test@example.com"

        with patch("app.api.auth.get_supabase_admin") as mock_admin:
            mock_admin.return_value.auth.sign_in_with_password.return_value = mock_result
            r = client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "secret"},
            )

        assert r.status_code == 200
        assert "access_token" in r.cookies

    def test_invalid_credentials_returns_401(self) -> None:
        with patch("app.api.auth.get_supabase_admin") as mock_admin:
            mock_admin.return_value.auth.sign_in_with_password.side_effect = Exception("bad creds")
            r = client.post(
                "/api/auth/login",
                json={"email": "bad@example.com", "password": "wrong"},
            )

        assert r.status_code == 401

    def test_oauth_token_sets_cookie(self) -> None:
        with patch("app.api.auth.verify_token", return_value=_mock_user()):
            r = client.post("/api/auth/login", json={"access_token": "google-tok"})

        assert r.status_code == 200
        assert "access_token" in r.cookies

    def test_invalid_oauth_token_returns_401(self) -> None:
        with patch("app.api.auth.verify_token", side_effect=Exception("bad token")):
            r = client.post("/api/auth/login", json={"access_token": "bad-tok"})

        assert r.status_code == 401

    def test_missing_credentials_returns_422(self) -> None:
        r = client.post("/api/auth/login", json={})
        assert r.status_code == 422


class TestLogout:
    def test_returns_ok(self) -> None:
        r = client.post("/api/auth/logout")
        assert r.status_code == 200
        assert r.json() == {"ok": True}


class TestMe:
    def test_returns_user_when_authenticated(self) -> None:
        with patch("app.core.deps.verify_token", return_value=_mock_user()):
            r = client.get("/api/auth/me", cookies={"access_token": "valid-tok"})

        assert r.status_code == 200
        assert r.json()["email"] == "test@example.com"
        assert r.json()["id"] == "user-123"

    def test_returns_401_when_no_cookie(self) -> None:
        r = client.get("/api/auth/me")
        assert r.status_code == 401

    def test_returns_401_with_invalid_token(self) -> None:
        with patch("app.core.deps.verify_token", side_effect=Exception("expired")):
            r = client.get("/api/auth/me", cookies={"access_token": "expired-tok"})

        assert r.status_code == 401
