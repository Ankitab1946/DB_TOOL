from __future__ import annotations

import os
from fastapi import HTTPException, Request

from DataDictionaryAdminApp.config import get_settings


def current_user(request: Request) -> str:
    return (
        request.headers.get("X-App-User")
        or request.headers.get("X-Forwarded-User")
        or os.getenv("USERNAME")
        or os.getenv("USER")
        or get_settings().default_user
        or "sysuser"
    )


def current_role(request: Request) -> str:
    """Resolve the UI/application role. Explicit ADMIN/USER header wins.

    API clients that do not send X-App-Role keep the previous username-based
    admin behavior for backward compatibility.
    """
    requested = (request.headers.get("X-App-Role") or "").strip().upper()
    if requested in {"ADMIN", "USER"}:
        return requested
    return "ADMIN" if get_settings().is_admin(current_user(request)) else "USER"


def require_admin(request: Request) -> str:
    user = current_user(request)
    if current_role(request) == "ADMIN":
        return user
    raise HTTPException(status_code=403, detail="Admin access is required for this operation.")
