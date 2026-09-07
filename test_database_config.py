from DataDictionaryAdminApp.config import Settings


def test_sqlserver_url_and_environment_resolution():
    settings = Settings(
        _env_file=None,
        app_environments="LOCAL,DEV",
        selected_environment="DEV",
        selected_db_type="SQLSERVER",
        sqlserver_server="sql-host",
        sqlserver_database="PRJ_DB",
        enable_sqlserver=True,
    )
    cfg = settings.database_config("DEV", "SQLSERVER")
    assert cfg["db_type"] == "SQLSERVER"
    assert cfg["database"] == "PRJ_DB"
    assert settings.sqlalchemy_url("DEV", "SQLSERVER").drivername == "mssql+pyodbc"


def test_postgres_url_and_environment_resolution():
    settings = Settings(
        _env_file=None,
        app_environments="LOCAL,DEV",
        selected_environment="DEV",
        selected_db_type="POSTGRES",
        pg_host="pg-host",
        pg_port=5432,
        pg_database="PRJ_DB",
        pg_schema="prj_dbd",
        postgres_user="app",
        postgres_password="secret",
        enable_postgres=True,
    )
    cfg = settings.database_config("DEV", "POSTGRES")
    url = settings.sqlalchemy_url("DEV", "POSTGRES")
    assert cfg["db_type"] == "POSTGRES"
    assert cfg["host"] == "pg-host"
    assert cfg["schema"] == "prj_dbd"
    assert url.drivername == "postgresql+psycopg"
    assert url.database == "PRJ_DB"


def test_postgres_pg_environment_variable_names(monkeypatch):
    monkeypatch.setenv("ENV_DEV_PG_HOST", "pg-dev-host")
    monkeypatch.setenv("ENV_DEV_PG_PORT", "5544")
    monkeypatch.setenv("ENV_DEV_PG_DATABASE", "PG_DEV_DB")
    monkeypatch.setenv("ENV_DEV_PG_SCHEMA", "prj_dbd")

    settings = Settings(
        _env_file=None,
        app_environments="LOCAL,DEV",
        selected_environment="DEV",
        selected_db_type="POSTGRES",
        pg_host="fallback-host",
        pg_port=5432,
        pg_database="fallback-db",
        pg_schema="fallback-schema",
        postgres_user="app",
        postgres_password="secret",
        enable_postgres=True,
    )
    cfg = settings.database_config("DEV", "POSTGRES")
    assert cfg["host"] == "pg-dev-host"
    assert cfg["port"] == 5544
    assert cfg["database"] == "PG_DEV_DB"
    assert cfg["schema"] == "prj_dbd"
    url = settings.sqlalchemy_url("DEV", "POSTGRES")
    assert url.host == "pg-dev-host"
    assert url.port == 5544
    assert url.database == "PG_DEV_DB"
