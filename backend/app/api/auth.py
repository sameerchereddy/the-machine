from fastapi import APIRouter, HTTPException, Response, status
from pydantic import BaseModel

from app.core.deps import CurrentUser
from app.core.security import get_supabase_admin, verify_token

router = APIRouter(prefix="/api/auth", tags=["auth"])

_COOKIE = "access_token"
_COOKIE_MAX_AGE = 60 * 60 * 8  # 8 hours


class LoginRequest(BaseModel):
    email: str | None = None
    password: str | None = None
    access_token: str | None = None  # OAuth token from Supabase JS (e.g. Google SSO)


def _set_auth_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=_COOKIE,
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # TODO: True in production
        max_age=_COOKIE_MAX_AGE,
    )


@router.post("/login")
def login(body: LoginRequest, response: Response) -> dict[str, object]:
    if body.access_token:
        try:
            user = verify_token(body.access_token)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
            ) from None
        _set_auth_cookie(response, body.access_token)
        return {"user": user}

    if body.email and body.password:
        try:
            result = get_supabase_admin().auth.sign_in_with_password(
                {"email": body.email, "password": body.password}
            )
            if result.session is None or result.user is None:
                raise ValueError("No session returned")
            token = result.session.access_token
            user = {"id": str(result.user.id), "email": result.user.email or ""}
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            ) from None
        _set_auth_cookie(response, token)
        return {"user": user}

    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail="Provide email+password or access_token",
    )


@router.post("/logout")
def logout(response: Response) -> dict[str, bool]:
    response.delete_cookie(_COOKIE)
    return {"ok": True}


@router.get("/me")
def me(current_user: CurrentUser) -> dict[str, str]:
    return current_user
