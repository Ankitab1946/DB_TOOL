from fastapi import APIRouter, Request

from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.utils.security import current_role, current_user

router = APIRouter(tags=["System"])


@router.get("/health")
def health():
    return {"status": "ok", "version": "2.0.0"}


@router.get("/system/context")
def context(request: Request):
    settings = get_settings()
    environment = settings.resolve_environment(request.headers.get("X-App-Environment"))
    db_type = settings.resolve_db_type(request.headers.get("X-DB-Type"))
    cfg = settings.database_config(environment, db_type)
    user = current_user(request)
    role = current_role(request)
    if db_type == "POSTGRES":
        server = f"{cfg['host']}:{cfg['port']}"
    else:
        server = cfg["server"]
    return {
        "environment": environment,
        "environments": settings.available_environments(),
        "db_type": db_type,
        "db_types": settings.available_db_types(),
        "database": cfg["database"],
        "server": server,
        "database_enabled": cfg["enabled"],
        "current_user": user,
        "role": role,
        "is_admin": role == "ADMIN",
    }
