"""Central environment-aware application configuration.

Cloud configuration priority (highest to lowest):
1. Process environment variables (recommended for Kubernetes/Helm deployments).
2. Mounted config/secret files (``APP_CONFIG_DIR`` / ``CONFIG_DIR``).
3. YAML values file (``APP_CONFIG_FILE`` or environment-specific ``*-values.yaml``).
4. Local ``.env`` file (developer fallback only).
5. Application defaults.

This keeps local development convenient without requiring a ``.env`` file in DEV/UAT/PROD.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


SUPPORTED_DB_TYPES = ("SQLSERVER", "POSTGRES")
SUPPORTED_ENVIRONMENTS = ("LOCAL", "DEV", "UAT", "PROD")

# Keys that may be supplied as environment variables, YAML leaves, or mounted
# ConfigMap/Secret files. Environment-specific forms (ENV_DEV_*, etc.) are also
# accepted automatically.
_RUNTIME_KEYS = {
    "APP_NAME",
    "APP_ENV",
    "APP_ENVIRONMENTS",
    "SELECTED_ENVIRONMENT",
    "SELECTED_DB_TYPE",
    "API_BASE_URL",
    "SQLSERVER_SERVER",
    "SQLSERVER_DATABASE",
    "SQLSERVER_WINDOWS_AUTH",
    "SQLSERVER_USER",
    "SQLSERVER_PASSWORD",
    "SQLSERVER_DRIVER",
    "SQLSERVER_TRUST_CERT",
    "ENABLE_SQLSERVER",
    "PG_HOST",
    "PG_PORT",
    "PG_DATABASE",
    "PG_SCHEMA",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
    "POSTGRES_SSLMODE",
    "ENABLE_POSTGRES",
    "ADMIN_USERS",
    "DEFAULT_USER",
    "LOCAL_AUTO_ADMIN",
    "DATA_DICTIONARY_DEFAULT_PAGE_SIZE",
    "DATA_DICTIONARY_MAX_PAGE_SIZE",
    "SQLALCHEMY_POOL_SIZE",
    "SQLALCHEMY_MAX_OVERFLOW",
    "SQLALCHEMY_POOL_TIMEOUT_SECONDS",
    "SQLALCHEMY_POOL_RECYCLE_SECONDS",
    "SQLALCHEMY_POOL_PRE_PING",
    "DB_CONNECT_TIMEOUT_SECONDS",
    "API_READ_TIMEOUT_SECONDS",
    "API_WRITE_TIMEOUT_SECONDS",
    "EXCEL_TEMPLATE_VERSION",
    "MAX_UPLOAD_SIZE_MB",
    "S3_BUCKET_NAME",
    "S3_PREFIX",
    "AWS_REGION",
    "S3_ENDPOINT_URL",
    "S3_HOST",
    "S3_PORT",
    "S3_USE_SSL",
    "S3_VERIFY_SSL",
    "S3_ADDRESSING_STYLE",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
}


def _normalise_key(value: str) -> str:
    """Convert YAML/config-file keys such as ``pgHost`` into ``PG_HOST``."""
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", str(value).strip())
    text = re.sub(r"[^A-Za-z0-9]+", "_", text)
    return text.strip("_").upper()


def _scalar_text(value: Any) -> str | None:
    if value is None or isinstance(value, (dict, list, tuple, set)):
        return None
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_dotenv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {}
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = _normalise_key(key)
        if key:
            values[key] = value.strip().strip('"').strip("'")
    return values


def _dotenv_candidates() -> list[Path]:
    candidates = [Path.cwd() / ".env", *[parent / ".env" for parent in Path(__file__).resolve().parents]]
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _yaml_candidates(environment: str) -> list[Path]:
    """Return explicit and conventional Helm/config YAML locations.

    ``APP_CONFIG_FILE`` is the preferred cloud setting. Conventional locations
    are included so a mounted ``/config/dev-values.yaml`` also works without a
    local .env file.
    """
    candidates: list[Path] = []
    for variable in ("APP_CONFIG_FILE", "CONFIG_FILE", "VALUES_FILE", "HELM_VALUES_FILE"):
        value = os.getenv(variable, "").strip()
        if value:
            candidates.append(Path(value))

    env_name = (environment or "LOCAL").strip().lower()
    names = (f"{env_name}-values.yaml", f"values-{env_name}.yaml", f"{env_name}-values.yml", f"values-{env_name}.yml")
    roots = (
        Path.cwd(),
        Path.cwd() / "config",
        Path.cwd() / "deploy",
        Path("/config"),
        Path("/app/config"),
        Path("/etc/data-dictionary"),
    )
    for root in roots:
        for name in names:
            candidates.append(root / name)

    # Cloud deployments commonly mount/copy this exact filename. Probe all standard
    # locations even when SELECTED_ENVIRONMENT itself is defined inside the file.
    for root in roots:
        candidates.append(root / "dev-values.yaml")

    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _extract_yaml_values(document: Any) -> dict[str, str]:
    """Extract application settings from common Helm/YAML structures.

    Supported examples include:
      env: {PG_HOST: host}
      env: [{name: PG_HOST, value: host}]
      config: {PG_HOST: host}
      environments: {DEV: {PG_HOST: host}}
      database: {postgres: {host: host, port: 5432, ...}}

    Secret ``valueFrom`` references are intentionally not resolved here; Kubernetes
    should inject/mount those values into the running container.
    """
    result: dict[str, str] = {}

    semantic_postgres = {
        "HOST": "PG_HOST",
        "PORT": "PG_PORT",
        "DATABASE": "PG_DATABASE",
        "DB": "PG_DATABASE",
        "NAME": "PG_DATABASE",
        "SCHEMA": "PG_SCHEMA",
        "USER": "POSTGRES_USER",
        "USERNAME": "POSTGRES_USER",
        "PASSWORD": "POSTGRES_PASSWORD",
        "SSLMODE": "POSTGRES_SSLMODE",
        "SSL_MODE": "POSTGRES_SSLMODE",
        "ENABLED": "ENABLE_POSTGRES",
        "ENABLE": "ENABLE_POSTGRES",
    }

    def add(key: str, value: Any) -> None:
        text = _scalar_text(value)
        if text is None:
            return
        normalised = _normalise_key(key)
        if normalised:
            result[normalised] = text

    def walk(node: Any, path: tuple[str, ...] = ()) -> None:
        if isinstance(node, dict):
            # Kubernetes/Helm env list item: {name: PG_HOST, value: ...}
            lowered = {_normalise_key(k): v for k, v in node.items()}
            if "NAME" in lowered and "VALUE" in lowered:
                env_key = _normalise_key(str(lowered["NAME"]))
                if env_key:
                    add(env_key, lowered["VALUE"])

            for raw_key, value in node.items():
                key = _normalise_key(raw_key)
                next_path = (*path, key)

                # Direct canonical leaf key anywhere in a values/config tree.
                if key in _RUNTIME_KEYS or key.startswith("ENV_"):
                    add(key, value)

                # environments: DEV: PG_HOST: ... -> ENV_DEV_PG_HOST
                if len(next_path) >= 3 and next_path[-3] in {"ENVIRONMENTS", "ENVIRONMENT"}:
                    env_candidate = next_path[-2]
                    leaf = next_path[-1]
                    if env_candidate in SUPPORTED_ENVIRONMENTS and (leaf in _RUNTIME_KEYS or leaf.startswith("PG_") or leaf.startswith("POSTGRES_")):
                        add(f"ENV_{env_candidate}_{leaf}", value)

                # database.postgres.host style configuration.
                upper_path = set(next_path[:-1])
                if {"POSTGRES", "POSTGRESQL"} & upper_path and not isinstance(value, (dict, list)):
                    mapped = semantic_postgres.get(key)
                    if mapped:
                        add(mapped, value)

                # app.environment / app.db_type convenience aliases.
                if not isinstance(value, (dict, list)):
                    if key in {"ENVIRONMENT", "APP_ENVIRONMENT"} and ({"APP", "APPLICATION"} & upper_path):
                        add("SELECTED_ENVIRONMENT", value)
                    if key in {"DB_TYPE", "DATABASE_TYPE"} and ({"APP", "APPLICATION", "DATABASE"} & upper_path):
                        add("SELECTED_DB_TYPE", value)
                    if key in {"API_BASE_URL", "API_URL"} and ({"APP", "APPLICATION", "API"} & upper_path):
                        add("API_BASE_URL", value)

                walk(value, next_path)
        elif isinstance(node, list):
            for item in node:
                walk(item, path)

    walk(document)
    return result


def _read_yaml(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return _extract_yaml_values(document)


def _config_dir_candidates() -> list[Path]:
    candidates: list[Path] = []
    for variable in ("APP_CONFIG_DIR", "CONFIG_DIR", "K8S_CONFIG_DIR"):
        value = os.getenv(variable, "").strip()
        if value:
            candidates.append(Path(value))
    candidates.extend((Path("/config"), Path("/etc/data-dictionary/config"), Path("/app/config")))
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            unique.append(path)
            seen.add(key)
    return unique


def _read_mounted_config_dir(path: Path) -> dict[str, str]:
    """Read Kubernetes ConfigMap/Secret volume files (one setting per file)."""
    if not path.is_dir():
        return {}
    values: dict[str, str] = {}
    candidate_keys = set(_RUNTIME_KEYS)
    for env_name in SUPPORTED_ENVIRONMENTS:
        candidate_keys.update({f"ENV_{env_name}_{key}" for key in _RUNTIME_KEYS})
    for key in candidate_keys:
        for file_name in (key, key.lower()):
            file_path = path / file_name
            if not file_path.is_file():
                continue
            try:
                value = file_path.read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if value != "":
                values[key] = value
            break
    return values


def runtime_config_values(environment: str | None = None) -> tuple[dict[str, str], list[str]]:
    """Load non-process configuration sources without requiring ``.env``.

    The returned values are ordered by source priority before process environment
    variables are considered: local .env < YAML < mounted config files.
    """
    selected_env = (environment or os.getenv("SELECTED_ENVIRONMENT") or os.getenv("APP_ENV") or "LOCAL").strip().upper()
    values: dict[str, str] = {}
    sources: list[str] = []

    # Local developer fallback. Missing .env is normal in cloud and is not an error.
    for path in _dotenv_candidates():
        loaded = _parse_dotenv(path)
        if loaded:
            values.update(loaded)
            sources.append(str(path))
            break

    # Explicit/conventional values YAML overrides local .env.
    for path in _yaml_candidates(selected_env):
        loaded = _read_yaml(path)
        if loaded:
            values.update(loaded)
            sources.append(str(path))
            # Explicit APP_CONFIG_FILE is authoritative; for conventional files use first match.
            break

    # Mounted ConfigMap/Secret files override YAML/local fallback.
    for path in _config_dir_candidates():
        loaded = _read_mounted_config_dir(path)
        if loaded:
            values.update(loaded)
            sources.append(str(path))
            # Merge only one mounted config root to avoid ambiguous deployments.
            break

    return values, sources


def bootstrap_runtime_config(environment: str | None = None) -> list[str]:
    """Populate missing process settings from cloud/local configuration sources.

    Existing process environment variables are never overwritten, so values
    injected by Helm/Kubernetes remain the highest-priority source.
    """
    values, sources = runtime_config_values(environment)
    for key, value in values.items():
        os.environ.setdefault(key, value)
    return sources


class Settings(BaseSettings):
    # .env is deliberately NOT configured as a mandatory/implicit Pydantic source.
    # bootstrap_runtime_config() provides local .env fallback while cloud can run
    # entirely from injected env vars, ConfigMap/Secret files, or values YAML.
    model_config = SettingsConfigDict(env_file=None, extra="ignore", case_sensitive=False)

    app_name: str = "PRJ Data Dictionary Administration Platform"
    app_env: str = "LOCAL"
    app_environments: str = "LOCAL,DEV,UAT,PROD"
    selected_environment: str = "LOCAL"
    selected_db_type: str = "POSTGRES"
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

    def __init__(self, **values: Any):
        # Make direct Settings() construction cloud-config aware as well.
        bootstrap_runtime_config(values.get("selected_environment"))
        super().__init__(**values)

    def available_environments(self) -> list[str]:
        return [item.strip().upper() for item in self.app_environments.split(",") if item.strip()]

    def available_db_types(self) -> list[str]:
        return list(SUPPORTED_DB_TYPES)

    def resolve_environment(self, environment: str | None = None) -> str:
        candidate = (environment or self.selected_environment or self.app_env).strip().upper()
        return candidate if candidate in self.available_environments() else self.app_env.upper()

    def resolve_db_type(self, db_type: str | None = None) -> str:
        candidate = (db_type or self.selected_db_type or "POSTGRES").strip().upper()
        aliases = {"POSTGRESQL": "POSTGRES", "MSSQL": "SQLSERVER", "SQL SERVER": "SQLSERVER"}
        candidate = aliases.get(candidate, candidate)
        return candidate if candidate in SUPPORTED_DB_TYPES else "POSTGRES"

    @staticmethod
    def _as_bool(value: Any) -> bool:
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    def _env_value(self, environment: str, suffix: str, default: Any) -> Any:
        # Environment-specific values win; generic values are the deployment-level fallback.
        value = os.getenv(f"ENV_{environment}_{suffix}")
        if value is None or value == "":
            value = os.getenv(suffix)
        return default if value is None or value == "" else value

    def database_config(self, environment: str | None = None, db_type: str | None = None) -> dict[str, Any]:
        env = self.resolve_environment(environment)
        kind = self.resolve_db_type(db_type)
        # If an explicit environment is selected at request time, allow an environment-specific
        # values YAML/config mount to contribute before resolving the DB settings.
        bootstrap_runtime_config(env)
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
    bootstrap_runtime_config()
    return Settings()
