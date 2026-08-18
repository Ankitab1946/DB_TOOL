/* SQL Server / Azure SQL schema validation.
   READ ONLY. Run AFTER 003_add_scoped_definition_segment.sql on an existing DB.
   Returns PASS/FAIL rows and exact remediation. */
SET NOCOUNT ON;

DECLARE @checks TABLE(
    object_type varchar(20) NOT NULL,
    schema_name sysname NULL,
    table_name sysname NULL,
    column_name sysname NULL,
    status varchar(10) NOT NULL,
    fix_hint nvarchar(600) NULL
);

/* Required schema/tables. */
INSERT @checks VALUES
('SCHEMA',N'stg',NULL,NULL,CASE WHEN SCHEMA_ID(N'stg') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Run the baseline schema setup; stg schema is required.'),
('TABLE',N'dbo',N'raw_prj_attribute_new_test',NULL,CASE WHEN OBJECT_ID(N'dbo.raw_prj_attribute_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Application raw table is required.'),
('TABLE',N'dbo',N'prj_portfolio_reference_new_test',NULL,CASE WHEN OBJECT_ID(N'dbo.prj_portfolio_reference_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Portfolio reference table is required.'),
('TABLE',N'dbo',N'audit_table_new_test',NULL,CASE WHEN OBJECT_ID(N'dbo.audit_table_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Audit table is required.'),
('TABLE',N'stg',N'prj_attribute_master_new_test',NULL,CASE WHEN OBJECT_ID(N'stg.prj_attribute_master_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Staging master table is required.'),
('TABLE',N'stg',N'prj_attribute_business_rules_new_test',NULL,CASE WHEN OBJECT_ID(N'stg.prj_attribute_business_rules_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Staging business-rules table is required.'),
('TABLE',N'dbo',N'prj_attribute_master_new_test',NULL,CASE WHEN OBJECT_ID(N'dbo.prj_attribute_master_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Final master table is required.'),
('TABLE',N'dbo',N'prj_attribute_business_rules_new_test',NULL,CASE WHEN OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test',N'U') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Final business-rules table is required.');

/* External source dependency: singular or plural table name is accepted. */
DECLARE @source_table nvarchar(300)=CASE
    WHEN OBJECT_ID(N'dbo.prj_data_sources',N'U') IS NOT NULL THEN N'dbo.prj_data_sources'
    WHEN OBJECT_ID(N'dbo.prj_data_source',N'U') IS NOT NULL THEN N'dbo.prj_data_source'
    ELSE NULL END;

INSERT @checks VALUES('TABLE',N'dbo',N'prj_data_sources / prj_data_source',NULL,
    CASE WHEN @source_table IS NOT NULL THEN 'OK' ELSE 'MISSING' END,
    N'Existing read-only source table is required; it is intentionally not created by this application.');

DECLARE @required TABLE(schema_name sysname,table_name sysname,column_name sysname,fix_hint nvarchar(600));
INSERT @required VALUES
/* raw */
(N'dbo',N'raw_prj_attribute_new_test',N'portfolio',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'prj_id',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'prj_attribute_name',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'prj_physical_attribute_name',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'section',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'sub_section',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'data_type',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'calculated_or_reported',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'calculation_logic',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'segment',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'attribute_definition',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'attribute_description',NULL),
(N'dbo',N'raw_prj_attribute_new_test',N'display_order',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'tech_logic',NULL),(N'dbo',N'raw_prj_attribute_new_test',N'display_name',NULL),
/* canonical staging master */
(N'stg',N'prj_attribute_master_new_test',N'prj_id',NULL),(N'stg',N'prj_attribute_master_new_test',N'prj_attribute_name',NULL),
(N'stg',N'prj_attribute_master_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql. It creates/backfills this from cfv_attribute_definition/attribute_definition when present.'),
(N'stg',N'prj_attribute_master_new_test',N'prj_physical_attribute_name',NULL),
(N'stg',N'prj_attribute_master_new_test',N'where_in_financial_statement',N'Run 003_add_scoped_definition_segment.sql. It creates/backfills this from segment when present.'),
/* staging rules */
(N'stg',N'prj_attribute_business_rules_new_test',N'scope_id',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'prj_id',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'port_ref_id',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'source_abbr_name',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'editable',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'symbol',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'mapping_type',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'calculation_logic',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql.'),
(N'stg',N'prj_attribute_business_rules_new_test',N'prj_attribute_description',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'segment',N'Run 003_add_scoped_definition_segment.sql.'),
(N'stg',N'prj_attribute_business_rules_new_test',N'tech_logic',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'display_order',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'display_name',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'section',NULL),
(N'stg',N'prj_attribute_business_rules_new_test',N'subsection',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'prompt_description',NULL),(N'stg',N'prj_attribute_business_rules_new_test',N'examples',NULL),
/* canonical final master */
(N'dbo',N'prj_attribute_master_new_test',N'prj_id',NULL),(N'dbo',N'prj_attribute_master_new_test',N'prj_attribute_name',NULL),
(N'dbo',N'prj_attribute_master_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql. It creates/backfills this from cfv_attribute_definition/attribute_definition when present.'),
(N'dbo',N'prj_attribute_master_new_test',N'prj_physical_attribute_name',NULL),
(N'dbo',N'prj_attribute_master_new_test',N'where_in_financial_statement',N'Run 003_add_scoped_definition_segment.sql. It creates/backfills this from segment when present.'),
/* final rules */
(N'dbo',N'prj_attribute_business_rules_new_test',N'scope_id',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_id',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'port_ref_id',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'source_abbr_name',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'editable',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'symbol',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'mapping_type',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'calculation_logic',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_attribute_definition',N'Run 003_add_scoped_definition_segment.sql.'),
(N'dbo',N'prj_attribute_business_rules_new_test',N'prj_attribute_description',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'segment',N'Run 003_add_scoped_definition_segment.sql.'),
(N'dbo',N'prj_attribute_business_rules_new_test',N'tech_logic',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'display_order',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'display_name',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'section',NULL),
(N'dbo',N'prj_attribute_business_rules_new_test',N'subsection',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'prompt_description',NULL),(N'dbo',N'prj_attribute_business_rules_new_test',N'examples',NULL);

INSERT @checks(object_type,schema_name,table_name,column_name,status,fix_hint)
SELECT 'COLUMN',r.schema_name,r.table_name,r.column_name,
       CASE WHEN OBJECT_ID(QUOTENAME(r.schema_name)+N'.'+QUOTENAME(r.table_name),N'U') IS NULL THEN 'SKIP'
            WHEN COL_LENGTH(r.schema_name+N'.'+r.table_name,r.column_name) IS NOT NULL THEN 'OK'
            ELSE 'MISSING' END,
       COALESCE(r.fix_hint,N'Column is required by the current application runtime contract.')
FROM @required r;

IF @source_table IS NOT NULL
BEGIN
    INSERT @checks VALUES('COLUMN',N'dbo',PARSENAME(@source_table,1),N'source_code',CASE WHEN COL_LENGTH(@source_table,N'source_code') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Read-only source lookup must expose source_code.');
    INSERT @checks VALUES('COLUMN',N'dbo',PARSENAME(@source_table,1),N'source_name',CASE WHEN COL_LENGTH(@source_table,N'source_name') IS NOT NULL THEN 'OK' ELSE 'MISSING' END,N'Read-only source lookup must expose source_name.');
END;

/* Always return the complete diagnostic grid first. */
SELECT object_type,schema_name,table_name,column_name,status,fix_hint
FROM @checks
ORDER BY CASE status WHEN 'MISSING' THEN 0 WHEN 'SKIP' THEN 1 ELSE 2 END,object_type,schema_name,table_name,column_name;

IF EXISTS(SELECT 1 FROM @checks WHERE status='MISSING')
BEGIN
    SELECT N'Schema validation failed' AS validation_result,
           COUNT(*) AS missing_count
    FROM @checks WHERE status='MISSING';
    THROW 51010,'Schema validation failed. The result grid above identifies every missing runtime object.',1;
END;

SELECT N'Schema validation passed' AS validation_result,0 AS missing_count;
