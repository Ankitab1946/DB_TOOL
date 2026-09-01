"""Authoritative logical table contract.

SQL Server uses the logical schemas directly (dbo/stg). PostgreSQL translates
``dbo -> prj_dbd`` and ``stg -> prj_stage`` in the SQLAlchemy engine.
"""

RAW_ATTRIBUTE = "dbo.raw_prj_attribute_new_test"
PORTFOLIO_REFERENCE = "dbo.prj_portfolio_reference_new_test"
POSTGRES_PORTFOLIO_REFERENCE = "prj_dbd.prj_portfolio_reference"
DATA_SOURCES = "dbo.prj_data_sources"  # Existing read-only dependency. Never created by this app.
AUDIT = "dbo.audit_table_new_test"
STG_ATTRIBUTE_MASTER = "stg.prj_attribute_master_new_test"
STG_ATTRIBUTE_BUSINESS_RULES = "stg.prj_attribute_business_rules_new_test"
STG_ATTRIBUTE_DISPLAY = "stg.prj_attribute_display_test"
ATTRIBUTE_MASTER = "dbo.prj_attribute_master_new_test"
ATTRIBUTE_BUSINESS_RULES = "dbo.prj_attribute_business_rules_new_test"
ATTRIBUTE_DISPLAY = "dbo.prj_attribute_display_test"

POSTGRES_SCHEMA_MAP = {"dbo": "prj_dbd", "stg": "prj_stage"}

APPLICATION_MANAGED_TABLES = (
    RAW_ATTRIBUTE,
    PORTFOLIO_REFERENCE,
    AUDIT,
    STG_ATTRIBUTE_MASTER,
    STG_ATTRIBUTE_BUSINESS_RULES,
    STG_ATTRIBUTE_DISPLAY,
    ATTRIBUTE_MASTER,
    ATTRIBUTE_BUSINESS_RULES,
    ATTRIBUTE_DISPLAY,
)

S3_EXPORTS = (
    ("prj_attribute_master_new_test", ATTRIBUTE_MASTER),
    ("prj_attribute_business_rules_new_test", ATTRIBUTE_BUSINESS_RULES),
)

RAW_FIELDS = (
    "portfolio",
    "prj_id",
    "prj_attribute_name",
    "prj_physical_attribute_name",
    "section",
    "sub_section",
    "data_type",
    "calculated_or_reported",
    "calculation_logic",
    "segment",
    "report_type",
    "attribute_definition",
    "attribute_description",
    "display_order",
    "tech_logic",
    "display_name",
)

MASTER_FIELDS = (
    "prj_id",
    "prj_attribute_name",
    "prj_attribute_definition",
    "prj_physical_attribute_name",
    "where_in_financial_statement",
)

BUSINESS_RULE_FIELDS = (
    "scope_id",
    "prj_id",
    "port_ref_id",
    "source_abbr_name",
    "prompt_description",
    "examples_for_llm",
    "editable",
    "data_type",
    "attribute_type",
    "business_logic",
    "calculation_logic",
)

DISPLAY_FIELDS = (
    "display_id",
    "scope_id",
    "display_order",
    "prj_id",
    "display_name",
    "section",
    "subsection",
    "prj_attribute_definition",
    "prj_attribute_description",
    "segment",
    "report_type",
)
