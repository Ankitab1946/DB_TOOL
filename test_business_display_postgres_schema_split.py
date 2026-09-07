from pathlib import Path

from DataDictionaryAdminApp.model.entities import (
    AttributeBusinessRule,
    AttributeDisplay,
    StagingAttributeDisplay,
    StagingBusinessRule,
)


BUSINESS_COLUMNS = [
    "scope_id", "prj_id", "port_ref_id", "source_abbr_name",
    "prompt_description", "examples_for_llm", "editable", "data_type",
    "attribute_type", "business_logic", "calculation_logic", "created_at",
    "updated_at", "created_by", "updated_by",
]

DISPLAY_REQUIRED = {
    "display_id", "scope_id", "display_order", "prj_id", "display_name",
    "section", "subsection", "created_at", "updated_at", "created_by", "updated_by",
}
DISPLAY_COMPAT_SCOPE = {
    "prj_attribute_definition", "prj_attribute_description", "segment", "report_type",
}


def test_business_rule_tables_have_only_business_columns():
    assert list(StagingBusinessRule.__table__.columns.keys()) == BUSINESS_COLUMNS
    assert list(AttributeBusinessRule.__table__.columns.keys()) == BUSINESS_COLUMNS


def test_display_tables_have_requested_columns_and_prior_scope_fields():
    for model in (StagingAttributeDisplay, AttributeDisplay):
        columns = set(model.__table__.columns.keys())
        assert DISPLAY_REQUIRED <= columns
        assert DISPLAY_COMPAT_SCOPE <= columns
        unique_scope_constraints = [
            c for c in model.__table__.constraints
            if c.__class__.__name__ == "UniqueConstraint"
            and [col.name for col in c.columns] == ["scope_id"]
        ]
        assert unique_scope_constraints


def test_postgres_runtime_translates_logical_schemas():
    text = Path("src/DataDictionaryAdminApp/core/database.py").read_text(encoding="utf-8")
    assert 'schema_translate_map={"stg": "prj_stage", "dbo": str(cfg.get("schema") or "prj_dbd")}' in text


def test_postgres_ddl_and_migration_use_required_physical_schemas():
    ddl = Path("src/DataDictionaryAdminApp/sql/postgres/001_create_tables.sql").read_text(encoding="utf-8").lower()
    migration = Path("src/DataDictionaryAdminApp/sql/postgres/005_split_business_display_and_schemas.sql").read_text(encoding="utf-8").lower()
    assert "create schema if not exists prj_stage" in ddl
    assert "create schema if not exists prj_dbd" in ddl
    assert "prj_stage.prj_attribute_display_test" in ddl
    assert "prj_dbd.prj_attribute_display_test" in ddl
    assert "alter table dbo." in migration
    assert "set schema prj_dbd" in migration
    assert "alter table stg." in migration
    assert "set schema prj_stage" in migration


def test_sqlserver_005_preserves_scope_id_while_splitting():
    migration = Path("src/DataDictionaryAdminApp/sql/005_split_business_display.sql").read_text(encoding="utf-8").lower()
    assert "identity_insert stg.prj_attribute_business_rules_new_test_v2 on" in migration
    assert "identity_insert dbo.prj_attribute_business_rules_new_test_v2 on" in migration
    assert "create table stg.prj_attribute_display_test" in migration
    assert "create table dbo.prj_attribute_display_test" in migration
