from supabase import Client, create_client

from app.core.config import settings


def get_supabase_admin() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_key)


def verify_token(token: str) -> dict[str, str]:
    """Verify a Supabase JWT via the admin API. Returns {id, email}."""
    response = get_supabase_admin().auth.get_user(token)
    if response is None or response.user is None:
        raise ValueError("Token is invalid or expired")
    return {"id": str(response.user.id), "email": response.user.email or ""}
