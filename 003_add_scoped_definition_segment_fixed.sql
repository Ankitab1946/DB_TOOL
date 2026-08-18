/* Existing SQL Server / Azure SQL databases:
   add per-scope Attribute Definition and Segment without dropping/recreating data.

   IMPORTANT:
   SQL Server compiles a T-SQL batch before executing it. Therefore a column added by
   ALTER TABLE cannot be referenced by a normal UPDATE later in the same batch on all
   SQL Server versions/configurations. The backfill below intentionally uses dynamic
   SQL (sp_executesql) so the UPDATE is compiled only after the columns exist.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    /* Fail early with a useful message if this is not the expected application schema. */
    IF OBJECT_ID(N'stg.prj_attribute_master_new_test', N'U') IS NULL
        THROW 51101, 'Required table stg.prj_attribute_master_new_test does not exist. Run the correct baseline schema migration first.', 1;
    IF OBJECT_ID(N'stg.prj_attribute_business_rules_new_test', N'U') IS NULL
        THROW 51102, 'Required table stg.prj_attribute_business_rules_new_test does not exist. Run the correct baseline schema migration first.', 1;
    IF OBJECT_ID(N'dbo.prj_attribute_master_new_test', N'U') IS NULL
        THROW 51103, 'Required table dbo.prj_attribute_master_new_test does not exist. Run the correct baseline schema migration first.', 1;
    IF OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test', N'U') IS NULL
        THROW 51104, 'Required table dbo.prj_attribute_business_rules_new_test does not exist. Run the correct baseline schema migration first.', 1;

    /* Add the new scope-level columns. Add segment nullable first, backfill it,
       then make it NOT NULL and attach the default. This is safe for populated tables. */
    IF COL_LENGTH(N'stg.prj_attribute_business_rules_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD prj_attribute_definition nvarchar(max) NULL;';

    IF COL_LENGTH(N'stg.prj_attribute_business_rules_new_test', N'segment') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD segment nvarchar(255) NULL;';

    IF COL_LENGTH(N'dbo.prj_attribute_business_rules_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD prj_attribute_definition nvarchar(max) NULL;';

    IF COL_LENGTH(N'dbo.prj_attribute_business_rules_new_test', N'segment') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD segment nvarchar(255) NULL;';

    /* Determine the source definition columns. Current schema uses
       prj_attribute_definition. cfv_attribute_definition / attribute_definition are
       accepted only as migration-source aliases for older/customized installations. */
    DECLARE @stg_definition_source sysname =
        CASE
            WHEN COL_LENGTH(N'stg.prj_attribute_master_new_test', N'prj_attribute_definition') IS NOT NULL THEN N'prj_attribute_definition'
            WHEN COL_LENGTH(N'stg.prj_attribute_master_new_test', N'cfv_attribute_definition') IS NOT NULL THEN N'cfv_attribute_definition'
            WHEN COL_LENGTH(N'stg.prj_attribute_master_new_test', N'attribute_definition') IS NOT NULL THEN N'attribute_definition'
            ELSE NULL
        END;

    DECLARE @dbo_definition_source sysname =
        CASE
            WHEN COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'prj_attribute_definition') IS NOT NULL THEN N'prj_attribute_definition'
            WHEN COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'cfv_attribute_definition') IS NOT NULL THEN N'cfv_attribute_definition'
            WHEN COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'attribute_definition') IS NOT NULL THEN N'attribute_definition'
            ELSE NULL
        END;

    DECLARE @stg_segment_source sysname =
        CASE
            WHEN COL_LENGTH(N'stg.prj_attribute_master_new_test', N'where_in_financial_statement') IS NOT NULL THEN N'where_in_financial_statement'
            WHEN COL_LENGTH(N'stg.prj_attribute_master_new_test', N'segment') IS NOT NULL THEN N'segment'
            ELSE NULL
        END;

    DECLARE @dbo_segment_source sysname =
        CASE
            WHEN COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'where_in_financial_statement') IS NOT NULL THEN N'where_in_financial_statement'
            WHEN COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'segment') IS NOT NULL THEN N'segment'
            ELSE NULL
        END;

    IF @stg_definition_source IS NULL
        THROW 51105, 'No Attribute Definition source column found in stg.prj_attribute_master_new_test. Expected prj_attribute_definition (or migration alias cfv_attribute_definition/attribute_definition).', 1;
    IF @dbo_definition_source IS NULL
        THROW 51106, 'No Attribute Definition source column found in dbo.prj_attribute_master_new_test. Expected prj_attribute_definition (or migration alias cfv_attribute_definition/attribute_definition).', 1;
    IF @stg_segment_source IS NULL
        THROW 51107, 'No Segment source column found in stg.prj_attribute_master_new_test. Expected where_in_financial_statement (or segment).', 1;
    IF @dbo_segment_source IS NULL
        THROW 51108, 'No Segment source column found in dbo.prj_attribute_master_new_test. Expected where_in_financial_statement (or segment).', 1;

    /* Compile the backfill only after the target columns have been added. */
    DECLARE @sql nvarchar(max);

    SET @sql = N'
        UPDATE r
           SET r.prj_attribute_definition = COALESCE(r.prj_attribute_definition, m.' + QUOTENAME(@stg_definition_source) + N'),
               r.segment = CASE
                    WHEN r.segment IS NULL OR LTRIM(RTRIM(r.segment)) = N'''' OR r.segment = N''NA''
                    THEN COALESCE(CONVERT(nvarchar(255), m.' + QUOTENAME(@stg_segment_source) + N'), N''NA'')
                    ELSE r.segment
               END
          FROM stg.prj_attribute_business_rules_new_test AS r
          JOIN stg.prj_attribute_master_new_test AS m ON m.prj_id = r.prj_id;';
    EXEC sys.sp_executesql @sql;

    SET @sql = N'
        UPDATE r
           SET r.prj_attribute_definition = COALESCE(r.prj_attribute_definition, m.' + QUOTENAME(@dbo_definition_source) + N'),
               r.segment = CASE
                    WHEN r.segment IS NULL OR LTRIM(RTRIM(r.segment)) = N'''' OR r.segment = N''NA''
                    THEN COALESCE(CONVERT(nvarchar(255), m.' + QUOTENAME(@dbo_segment_source) + N'), N''NA'')
                    ELSE r.segment
               END
          FROM dbo.prj_attribute_business_rules_new_test AS r
          JOIN dbo.prj_attribute_master_new_test AS m ON m.prj_id = r.prj_id;';
    EXEC sys.sp_executesql @sql;

    /* Guarantee NOT NULL Segment after backfill. */
    EXEC sys.sp_executesql N'UPDATE stg.prj_attribute_business_rules_new_test SET segment = N''NA'' WHERE segment IS NULL OR LTRIM(RTRIM(segment)) = N'''';';
    EXEC sys.sp_executesql N'UPDATE dbo.prj_attribute_business_rules_new_test SET segment = N''NA'' WHERE segment IS NULL OR LTRIM(RTRIM(segment)) = N'''';';

    IF EXISTS (
        SELECT 1
        FROM sys.columns
        WHERE object_id = OBJECT_ID(N'stg.prj_attribute_business_rules_new_test')
          AND name = N'segment' AND is_nullable = 1
    )
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ALTER COLUMN segment nvarchar(255) NOT NULL;';

    IF EXISTS (
        SELECT 1
        FROM sys.columns
        WHERE object_id = OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test')
          AND name = N'segment' AND is_nullable = 1
    )
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ALTER COLUMN segment nvarchar(255) NOT NULL;';

    /* Add defaults only when the column does not already have one. */
    IF NOT EXISTS (
        SELECT 1
        FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(N'stg.prj_attribute_business_rules_new_test')
          AND c.name = N'segment'
    )
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD CONSTRAINT DF_stg_rules_new_segment DEFAULT(N''NA'') FOR segment;';

    IF NOT EXISTS (
        SELECT 1
        FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id = dc.parent_object_id AND c.column_id = dc.parent_column_id
        WHERE dc.parent_object_id = OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test')
          AND c.name = N'segment'
    )
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD CONSTRAINT DF_rules_new_segment DEFAULT(N''NA'') FOR segment;';

    COMMIT TRANSACTION;

    SELECT N'Migration completed successfully' AS migration_result,
           @stg_definition_source AS staging_definition_source,
           @dbo_definition_source AS final_definition_source,
           @stg_segment_source AS staging_segment_source,
           @dbo_segment_source AS final_segment_source;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
