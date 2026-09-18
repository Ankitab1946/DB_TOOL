"""SQLAlchemy session factory supporting SQL Server and PostgreSQL."""
from __future__ import annotations

from functools import lru_cache
import re

from fastapi import HTTPException, Request
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from DataDictionaryAdminApp.config import get_settings
from DataDictionaryAdminApp.core.target_tables import build_table_rewrites, target_table_names_from_headers


class Base(DeclarativeBase):
    pass


def _rewrite_qualified_table(statement: str, schema: str, old_name: str, new_name: str) -> str:
    """Rewrite one qualified table reference without touching column/alias names."""
    if old_name == new_name:
        return statement
    replacements = (
        (f"[{schema}].[{old_name}]", f"[{schema}].[{new_name}]"),
        (f'"{schema}"."{old_name}"', f'"{schema}"."{new_name}"'),
        (f'"{schema}".{old_name}', f'"{schema}".{new_name}'),
        (f'{schema}."{old_name}"', f'{schema}."{new_name}"'),
        (f"{schema}.{old_name}", f"{schema}.{new_name}"),
    )
    for source, target in replacements:
        statement = statement.replace(source, target)
    return statement


_PG_LEGACY_MASTER_COLUMN_RE = re.compile(r"(?<!%\()\bwhere_in_financial_statement\b(?!\)s)")


def _rewrite_postgres_master_segment_column(statement: str) -> str:
    """Map the legacy ORM master-column name to PostgreSQL's physical ``segment`` column.

    The Python/API contract intentionally keeps ``where_in_financial_statement`` so SQL Server
    remains unchanged. PostgreSQL master tables use ``segment`` physically. Bind parameter names
    such as ``%(where_in_financial_statement)s`` are deliberately preserved.
    """
    return _PG_LEGACY_MASTER_COLUMN_RE.sub("segment", statement)


@event.listens_for(Engine, "before_cursor_execute", retval=True)
def _apply_target_table_rewrites(conn, cursor, statement, parameters, context, executemany):
    """Apply request table overrides and PostgreSQL-only master-column translation."""
    rewrites = context.execution_options.get("target_table_rewrites") or ()
    for schema, old_name, new_name in rewrites:
        statement = _rewrite_qualified_table(statement, schema, old_name, new_name)
    # PostgreSQL physically stores the master segment field as ``segment``.
    # Apply this translation for every PostgreSQL connection, not only sessions
    # carrying a particular execution option.  This is a fail-safe for reflected
    # tables, custom target-table routing, Finalize/Discard, and any future
    # PostgreSQL execution path that may use a separately-derived OptionEngine.
    if conn.dialect.name == "postgresql" or context.execution_options.get("postgres_master_segment_column"):
        statement = _rewrite_postgres_master_segment_column(statement)
    return statement, parameters


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
            schema_translate_map={"stg": "prj_stage", "dbo": str(cfg.get("schema") or "prj_dbd")},
            postgres_master_segment_column=True,
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
            "issue": f"{kind} database access is disabled for environment {env}. Check runtime environment/config values (for example ENV_{env}_ENABLE_{kind} or ENABLE_{kind}).",
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
        cfg = settings.database_config(environment, db_type)
        target_names = target_table_names_from_headers(request.headers)
        rewrites = build_table_rewrites(db_type, str(cfg.get("schema") or "prj_dbd"), target_names)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=422 if isinstance(exc, ValueError) else 503, detail=str(exc)) from exc

    # Bind this request to an OptionEngine that shares the normal connection pool
    # but carries its own target-table rewrite map across commits/transactions.
    base_bind = session_local.kw["bind"]
    request_bind = base_bind.execution_options(
        target_table_rewrites=rewrites,
        postgres_master_segment_column=(db_type == "POSTGRES"),
    )
    db = session_local(bind=request_bind)
    db.info["target_table_names"] = target_names
    db.info["pg_schema"] = str(cfg.get("schema") or "prj_dbd") if db_type == "POSTGRES" else "dbo"
    db.info["staging_schema"] = "prj_stage" if db_type == "POSTGRES" else "stg"
    try:
        yield db
    finally:
        db.close()
