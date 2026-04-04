from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.core.security import verify_token


def get_current_user(
    access_token: Annotated[str | None, Cookie()] = None,
) -> dict[str, str]:
    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    try:
        return verify_token(access_token)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        ) from None


CurrentUser = Annotated[dict[str, str], Depends(get_current_user)]
