"""Central environment-aware application configuration."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


SUPPORTED_DB_TYPES = ("SQLSERVER", "POSTGRES")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)

    app_name: str = "PRJ Data Dictionary Administration Platform"
    app_env: str = "LOCAL"
    app_environments: str = "LOCAL,DEV,UAT,PROD"
    selected_environment: str = "LOCAL"
    selected_db_type: str = "SQLSERVER"
    api_base_url: str = "http://localhost:8503/api/v1"

    sqlserver_server: str = r"localhost\SQLEXPRESS"
    sqlserver_database: str = "PRJ_DB"
    sqlserver_windows_auth: bool = True
    sqlserver_user: str = ""
    sqlserver_password: str = ""
    sqlserver_driver: str = "ODBC Driver 18 for SQL Server"
    sqlserver_trust_cert: str = "yes"
    enable_sqlserver: bool = False

    pg_host: str = "localhost"
    pg_port: int = 5432
    pg_database: str = "PRJ_DB"
    pg_schema: str = "prj_dbd"
    postgres_user: str = "postgres"
    postgres_password: str = ""
    postgres_sslmode: str = "prefer"
    enable_postgres: bool = False

    admin_users: str = "*,sysuser"
    default_user: str = "sysuser"
    local_auto_admin: bool = True
    data_dictionary_default_page_size: int = 100
    data_dictionary_max_page_size: int = 1000
    sqlalchemy_pool_size: int = 5
    sqlalchemy_max_overflow: int = 10
    sqlalchemy_pool_timeout_seconds: int = 30
    sqlalchemy_pool_recycle_seconds: int = 1800
    sqlalchemy_pool_pre_ping: bool = False
    db_connect_timeout_seconds: int = 30
    api_read_timeout_seconds: int = 120
    api_write_timeout_seconds: int = 600
    excel_template_version: str = "2.0"
    max_upload_size_mb: int = 30

    s3_bucket_name: str = ""
    s3_prefix: str = "data-dictionary"
    aws_region: str = "ap-south-1"
    s3_endpoint_url: str = ""
    s3_host: str = ""
    s3_port: str = ""
    s3_use_ssl: bool = True
    s3_verify_ssl: bool = False
    s3_addressing_style: str = "path"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    def available_environments(self) -> list[str]:
        return [item.strip().upper() for item in self.app_environments.split(",") if item.strip()]

    def available_db_types(self) -> list[str]:
        return list(SUPPORTED_DB_TYPES)

    def resolve_environment(self, environment: str | None = None) -> str:
        candidate = (environment or self.selected_environment or self.app_env).strip().upper()
        return candidate if candidate in self.available_environments() else self.app_env.upper()

    def resolve_db_type(self, db_type: str | None = None) -> str:
        candidate = (db_type or self.selected_db_type or "SQLSERVER").strip().upper()
        aliases = {"POSTGRESQL": "POSTGRES", "MSSQL": "SQLSERVER", "SQL SERVER": "SQLSERVER"}
        candidate = aliases.get(candidate, candidate)
        return candidate if candidate in SUPPORTED_DB_TYPES else "SQLSERVER"

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    @lru_cache(maxsize=1)
    def _dotenv_values() -> dict[str, str]:
        candidates = [Path.cwd() / ".env", *[parent / ".env" for parent in Path(__file__).resolve().parents]]
        for path in candidates:
            if not path.exists():
                continue
            values: dict[str, str] = {}
            for raw in path.read_text(encoding="utf-8").splitlines():
                line = raw.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip('"').strip("'")
            return values
        return {}

    def _env_value(self, environment: str, suffix: str, default: Any) -> Any:
        key = f"ENV_{environment}_{suffix}"
        value = os.getenv(key)
        if value is None or value == "":
            value = self._dotenv_values().get(key)
        return default if value is None or value == "" else value

    def database_config(self, environment: str | None = None, db_type: str | None = None) -> dict[str, Any]:
        env = self.resolve_environment(environment)
        kind = self.resolve_db_type(db_type)
        if kind == "POSTGRES":
            return {
                "environment": env,
                "db_type": kind,
                "host": self._env_value(env, "PG_HOST", self.pg_host),
                "port": int(self._env_value(env, "PG_PORT", self.pg_port)),
                "database": self._env_value(env, "PG_DATABASE", self.pg_database),
                "schema": self._env_value(env, "PG_SCHEMA", self.pg_schema),
                "user": self._env_value(env, "POSTGRES_USER", self.postgres_user),
                "password": self._env_value(env, "POSTGRES_PASSWORD", self.postgres_password),
                "sslmode": self._env_value(env, "POSTGRES_SSLMODE", self.postgres_sslmode),
                "enabled": self._as_bool(self._env_value(env, "ENABLE_POSTGRES", self.enable_postgres)),
            }
        return {
            "environment": env,
            "db_type": kind,
            "server": self._env_value(env, "SQLSERVER_SERVER", self.sqlserver_server),
            "database": self._env_value(env, "SQLSERVER_DATABASE", self.sqlserver_database),
            "windows_auth": self._as_bool(
                self._env_value(env, "SQLSERVER_WINDOWS_AUTH", self.sqlserver_windows_auth)
            ),
            "user": self._env_value(env, "SQLSERVER_USER", self.sqlserver_user),
            "password": self._env_value(env, "SQLSERVER_PASSWORD", self.sqlserver_password),
            "driver": self._env_value(env, "SQLSERVER_DRIVER", self.sqlserver_driver),
            "trust_cert": self._env_value(env, "SQLSERVER_TRUST_CERT", self.sqlserver_trust_cert),
            "enabled": self._as_bool(self._env_value(env, "ENABLE_SQLSERVER", self.enable_sqlserver)),
        }

    def sqlalchemy_url(self, environment: str | None = None, db_type: str | None = None):
        cfg = self.database_config(environment, db_type)
        if cfg["db_type"] == "POSTGRES":
            return URL.create(
                "postgresql+psycopg",
                username=cfg["user"],
                password=cfg["password"],
                host=cfg["host"],
                port=cfg["port"],
                database=cfg["database"],
                query={"sslmode": str(cfg["sslmode"])},
            )
        common = (
            f"DRIVER={{{cfg['driver']}}};SERVER={cfg['server']};DATABASE={cfg['database']};"
            f"Encrypt=no;TrustServerCertificate={cfg['trust_cert']};"
        )
        connection = common + ("Trusted_Connection=yes;" if cfg["windows_auth"] else f"UID={cfg['user']};PWD={cfg['password']};")
        return URL.create("mssql+pyodbc", query={"odbc_connect": connection})

    @property
    def effective_s3_endpoint_url(self) -> str:
        endpoint = self.s3_endpoint_url or self.s3_host
        if endpoint and self.s3_port and ":" not in endpoint.rsplit("/", 1)[-1]:
            endpoint = f"{endpoint.rstrip('/')}:{self.s3_port}"
        return endpoint

    def is_admin(self, username: str) -> bool:
        users = {value.strip().lower() for value in self.admin_users.split(",") if value.strip()}
        return "*" in users or username.lower() in users


@lru_cache
def get_settings() -> Settings:
    return Settings()
