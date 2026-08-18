/* SQL Server / Azure SQL schema validation.
   READ ONLY: this script does not alter tables or data.
   It returns exact missing objects/columns and then fails intentionally if the
   deployed DB is not aligned with the application contract. */
SET NOCOUNT ON;

DECLARE @missing TABLE(
    object_type varchar(20) NOT NULL,
    schema_name sysname NULL,
    table_name sysname NULL,
    column_name sysname NULL,
    fix_hint nvarchar(500) NULL
);

IF SCHEMA_ID(N'stg') IS NULL
    INSERT @missing VALUES('SCHEMA', N'stg', NULL, NULL, N'Create the stg schema or run 001_create_tables.sql for a new database.');

DECLARE @required_tables TABLE(schema_name sysname, table_name sysname, fix_hint nvarchar(500));
INSERT @required_tables VALUES
(N'dbo',N'raw_prj_attribute_new_test',N'Application managed table is missing. For a new DB run 001_create_tables.sql.'),
(N'dbo',N'prj_portfolio_reference_new_test',N'Application managed reference table is missing. For a new DB run 001_create_tables.sql.'),
(N'dbo',N'audit_table_new_test',N'Application managed audit table is missing. For a new DB run 001_create_tables.sql.'),
(N'stg',N'prj_attribute_master_new_test',N'Staging master table is missing. For a new DB run 001_create_tables.sql.'),
(N'stg',N'prj_attribute_business_rules_new_test',N'Staging business-rules table is missing. For a new DB run 001_create_tables.sql.'),
(N'dbo',N'prj_attribute_master_new_test',N'Final master table is missing. For a new DB run 001_create_tables.sql.'),
(N'dbo',N'prj_attribute_business_rules_new_test',N'Final business-rules table is missing. For a new DB run 001_create_tables.sql.');

INSERT @missing(object_type,schema_name,table_name,column_name,fix_hint)
SELECT 'TABLE', r.schema_name, r.table_name, NULL, r.fix_hint
FROM @required_tables r
WHERE OBJECT_ID(QUOTENAME(r.schema_name) + N'.' + QUOTENAME(r.table_name), N'U') IS NULL;

IF OBJECT_ID(N'dbo.prj_data_sources',N'U') IS NULL AND OBJECT_ID(N'dbo.prj_data_source',N'U') IS NULL
    INSERT @missing VALUES('TABLE',N'dbo',N'prj_data_sources',NULL,N'Read-only dependency is missing. dbo.prj_data_source (singular) is also accepted.');

DECLARE @required_columns TABLE(schema_name sysname, table_name sysname, column_name sysname, fix_hint nvarchar(500));
INSERT @required_columns VALUES
/* raw */
(N'dbo',N'raw_prj_attribute_new_test',N'portfolio',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'prj_id',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'prj_attribute_name',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'prj_physical_attribute_name',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'section',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'sub_section',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'data_type',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'calculated_or_reported',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'calculation_logic',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'segment',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'attribute_definition',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'attribute_description',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'display_order',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'tech_logic',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'display_name',NULL),
/* staging master */
(N'stg',N'prj_attribute_master_new_test',N'prj_id',NULL),(N'stg',N'prj_attribute_master_new_test',N'prj_attribute_name',NULL),
(N'stg',N'prj_attribute_master_new_test',N'prj_attribute_definition',N'Current application contract requires prj_attribute_definition.'),
(N'stg',N'prj_attribute_master_new_test',N'prj_physical_attribute_name',NULL),
(N'stg',N'prj_attribute_master_new_test',N'where_in_financial_statement',NULL),
/* staging rules */
(N'stg',N'prj_attribute_business_rules_new_test',N'scope_id',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'prj_id',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'port_ref_id',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'source_abbr_name',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'editable',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'symbol',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'mapping_type',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'calculation_logic',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql.'),
(N'stg',N'prj_attribute_business_rules_new_test',N'prj_attribute_description',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'segment',N'Run 003_add_scoped_definition_segment.sql.'),
(N'stg',N'prj_attribute_business_rules_new_test',N'tech_logic',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'display_order',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'display_name',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'section',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'subsection',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'prompt_description',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'examples',NULL),
/* final master */
(N'dbo',N'prj_attribute_master_new_test',N'prj_id',NULL),(N'dbo',N'prj_attribute_master_new_test',N'prj_attribute_name',NULL),
(N'dbo',N'prj_attribute_master_new_test',N'prj_attribute_definition',N'Current application contract requires prj_attribute_definition.'),
(N'dbo',N'prj_attribute_master_new_test',N'prj_physical_attribute_name',NULL),
(N'dbo',N'prj_attribute_master_new_test',N'where_in_financial_statement',NULL),
/* final rules */
(N'dbo',N'prj_attribute_business_rules_new_test',N'scope_id',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_id',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'port_ref_id',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'source_abbr_name',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'editable',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'symbol',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'mapping_type',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'calculation_logic',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql.'),
(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_attribute_description',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'segment',N'Run 003_add_scoped_definition_segment.sql.'),
(N'dbo',N'prj_attribute_business_rules_new_test',N'tech_logic',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'display_order',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'display_name',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'section',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'subsection',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'prompt_description',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'examples',NULL);

INSERT @missing(object_type,schema_name,table_name,column_name,fix_hint)
SELECT 'COLUMN', r.schema_name, r.table_name, r.column_name,
       COALESCE(r.fix_hint, N'Column is required by the current application schema. Compare with 001_create_tables.sql.')
FROM @required_columns r
WHERE OBJECT_ID(QUOTENAME(r.schema_name) + N'.' + QUOTENAME(r.table_name), N'U') IS NOT NULL
  AND COL_LENGTH(r.schema_name + N'.' + r.table_name, r.column_name) IS NULL;

/* External source-table minimum contract. */
DECLARE @source_table nvarchar(300) =
    CASE
        WHEN OBJECT_ID(N'dbo.prj_data_sources',N'U') IS NOT NULL THEN N'dbo.prj_data_sources'
        WHEN OBJECT_ID(N'dbo.prj_data_source',N'U') IS NOT NULL THEN N'dbo.prj_data_source'
        ELSE NULL
    END;

IF @source_table IS NOT NULL
BEGIN
    IF COL_LENGTH(@source_table, N'source_code') IS NULL
        INSERT @missing VALUES('COLUMN',N'dbo',PARSENAME(@source_table,1),N'source_code',N'Read-only source lookup must expose source_code.');
    IF COL_LENGTH(@source_table, N'source_name') IS NULL
        INSERT @missing VALUES('COLUMN',N'dbo',PARSENAME(@source_table,1),N'source_name',N'Read-only source lookup must expose source_name.');
END;

IF EXISTS (SELECT 1 FROM @missing)
BEGIN
    SELECT object_type,
           schema_name,
           table_name,
           column_name,
           fix_hint
    FROM @missing
    ORDER BY object_type, schema_name, table_name, column_name;

    THROW 51010, 'Schema validation failed. Review the detailed rows returned immediately above this error.', 1;
END;

SELECT N'Schema validation passed' AS validation_result;
