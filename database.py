"""SQLAlchemy session factory supporting SQL Server and PostgreSQL."""
from __future__ import annotations

from functools import lru_cache

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from DataDictionaryAdminApp.config import get_settings


class Base(DeclarativeBase):
    pass


@lru_cache(maxsize=16)
def _session_factory(environment: str, db_type: str):
    settings = get_settings()
    cfg = settings.database_config(environment, db_type)
    if not cfg["enabled"]:
        raise RuntimeError(f"{cfg['db_type']} database access is disabled for environment {cfg['environment']}.")

    connect_args = {}
    if cfg["db_type"] == "SQLSERVER":
        connect_args["timeout"] = settings.db_connect_timeout_seconds
    else:
        connect_args["connect_timeout"] = settings.db_connect_timeout_seconds

    engine_kwargs = {
        "future": True,
        "pool_pre_ping": settings.sqlalchemy_pool_pre_ping,
        "pool_use_lifo": True,
        "pool_size": settings.sqlalchemy_pool_size,
        "max_overflow": settings.sqlalchemy_max_overflow,
        "pool_timeout": settings.sqlalchemy_pool_timeout_seconds,
        "pool_recycle": settings.sqlalchemy_pool_recycle_seconds,
        "connect_args": connect_args,
    }
    if cfg["db_type"] == "SQLSERVER":
        engine_kwargs["fast_executemany"] = True

    engine = create_engine(
        settings.sqlalchemy_url(cfg["environment"], cfg["db_type"]),
        **engine_kwargs,
    )
    if cfg["db_type"] == "POSTGRES":
        # Keep one logical ORM model while PostgreSQL uses the required physical
        # schemas: all staging objects in prj_stage and all main/reference/raw/audit
        # objects in prj_dbd. SQL Server continues to use stg/dbo unchanged.
        engine = engine.execution_options(
            schema_translate_map={"stg": "prj_stage", "dbo": str(cfg.get("schema") or "prj_dbd")}
        )
    return sessionmaker(bind=engine, autocommit=False, autoflush=False, expire_on_commit=False)


def database_connection_status(environment: str, db_type: str) -> dict[str, object]:
    """Test the selected database with SELECT 1 and return a user-safe diagnostic."""
    settings = get_settings()
    env = settings.resolve_environment(environment)
    kind = settings.resolve_db_type(db_type)
    cfg = settings.database_config(env, kind)
    if not cfg["enabled"]:
        return {
            "connected": False,
            "environment": env,
            "db_type": kind,
            "database": cfg["database"],
            "issue": f"{kind} database access is disabled for environment {env}. Check ENV_{env}_ENABLE_{kind} in .env.",
        }

    connect_args: dict[str, object] = {}
    timeout = max(1, min(int(settings.db_connect_timeout_seconds), 5))
    if kind == "SQLSERVER":
        connect_args["timeout"] = timeout
    else:
        connect_args["connect_timeout"] = timeout

    engine = None
    try:
        engine = create_engine(
            settings.sqlalchemy_url(env, kind),
            future=True,
            pool_pre_ping=True,
            connect_args=connect_args,
        )
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {
            "connected": True,
            "environment": env,
            "db_type": kind,
            "database": cfg["database"],
            "issue": None,
        }
    except Exception as exc:  # driver-specific exception types differ between engines
        issue = str(getattr(exc, "orig", exc))
        password = str(cfg.get("password") or "")
        if password:
            issue = issue.replace(password, "***")
        return {
            "connected": False,
            "environment": env,
            "db_type": kind,
            "database": cfg["database"],
            "issue": issue[:1500],
        }
    finally:
        if engine is not None:
            engine.dispose()


def get_db(request: Request):
    settings = get_settings()
    environment = settings.resolve_environment(
        request.headers.get("X-App-Environment") or request.query_params.get("environment")
    )
    db_type = settings.resolve_db_type(request.headers.get("X-DB-Type") or request.query_params.get("db_type"))
    try:
        session_local = _session_factory(environment, db_type)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db = session_local()
    try:
        yield db
    finally:
        db.close()
