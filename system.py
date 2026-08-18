from fastapi import APIRouter, Depends, HTTPException, Request

from DataDictionaryAdminApp.api.schemas_api import CleanupRequest
from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.core.database import database_connection_status, get_db
from DataDictionaryAdminApp.repositories.data_dictionary_repository import DataDictionaryRepository
from DataDictionaryAdminApp.utils.security import current_role, current_user, require_admin
from sqlalchemy.orm import Session

router = APIRouter(tags=["System"])


@router.get("/health")
def health():
    return {
        "status": "ok",
        "version": "2.1.0",
        "upload_modes": ["MERGE", "INSERT_ONLY", "REPLACE"],
        "database_status_endpoint": True,
    }


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


@router.get("/system/database-status")
def database_status(request: Request):
    settings = get_settings()
    environment = settings.resolve_environment(request.headers.get("X-App-Environment"))
    db_type = settings.resolve_db_type(request.headers.get("X-DB-Type"))
    return database_connection_status(environment, db_type)


# Backward-compatibility alias for a typo that existed in some copied UI builds.
# Keep this hidden from Swagger so /system/database-status remains the canonical API.
@router.get("/system/database-sttaus", include_in_schema=False)
def database_status_typo_alias(request: Request):
    return database_status(request)


@router.post("/system/cleanup")
def cleanup_database(payload: CleanupRequest, request: Request, db: Session = Depends(get_db)):
    """Admin-only destructive cleanup of dictionary transactional/history data.

    The UI asks twice before calling this endpoint. The API independently requires
    both confirmations plus the exact phrase ``DELETE ALL DATA`` so a stray request
    cannot trigger deletion. Reference tables are intentionally preserved.
    """
    user = require_admin(request)
    if not payload.first_confirmation or not payload.second_confirmation:
        raise HTTPException(status_code=422, detail="Both cleanup confirmations are required.")
    if payload.confirmation_text.strip().upper() != "DELETE ALL DATA":
        raise HTTPException(status_code=422, detail="Type DELETE ALL DATA exactly to confirm cleanup.")

    try:
        deleted_by_table = DataDictionaryRepository(db).hard_delete_dictionary_data()
        db.commit()
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database cleanup failed: {exc}") from exc

    return {
        "message": "Database cleanup completed successfully.",
        "performed_by": user,
        "deleted_total": sum(deleted_by_table.values()),
        "deleted_by_table": deleted_by_table,
        "preserved_tables": [
            "dbo.prj_portfolio_reference_new_test (required seed rows port_ref_id 1-4)",
            "dbo.prj_data_sources (read-only external reference)",
        ],
    }
