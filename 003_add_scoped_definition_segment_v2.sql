/* Existing SQL Server / Azure SQL databases.
   Canonicalize master columns first, then add/backfill per-scope Definition + Segment.
   Safe to rerun. Does not drop tables or delete data.

   Why this version exists:
   - Some existing DBs use legacy aliases such as cfv_attribute_definition or attribute_definition.
   - The current application ORM requires canonical master columns:
       prj_attribute_definition
       where_in_financial_statement
   - SQL Server compiles a batch before executing it, therefore all statements that
     reference newly-added columns are executed through sp_executesql.
*/
SET NOCOUNT ON;
SET XACT_ABORT ON;

BEGIN TRY
    BEGIN TRANSACTION;

    IF SCHEMA_ID(N'stg') IS NULL
        THROW 51100, 'Required schema stg does not exist. Run the baseline schema setup first.', 1;

    IF OBJECT_ID(N'stg.prj_attribute_master_new_test', N'U') IS NULL
        THROW 51101, 'Required table stg.prj_attribute_master_new_test does not exist.', 1;
    IF OBJECT_ID(N'stg.prj_attribute_business_rules_new_test', N'U') IS NULL
        THROW 51102, 'Required table stg.prj_attribute_business_rules_new_test does not exist.', 1;
    IF OBJECT_ID(N'dbo.prj_attribute_master_new_test', N'U') IS NULL
        THROW 51103, 'Required table dbo.prj_attribute_master_new_test does not exist.', 1;
    IF OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test', N'U') IS NULL
        THROW 51104, 'Required table dbo.prj_attribute_business_rules_new_test does not exist.', 1;

    /* Capture legacy source columns BEFORE canonical columns are added. */
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

    /* ----------------------------------------------------------------------
       1) Canonicalize staging/final MASTER columns required by SQLAlchemy ORM.
       ---------------------------------------------------------------------- */
    IF COL_LENGTH(N'stg.prj_attribute_master_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_master_new_test ADD prj_attribute_definition nvarchar(max) NULL;';

    IF COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_master_new_test ADD prj_attribute_definition nvarchar(max) NULL;';

    IF COL_LENGTH(N'stg.prj_attribute_master_new_test', N'where_in_financial_statement') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_master_new_test ADD where_in_financial_statement nvarchar(255) NULL;';

    IF COL_LENGTH(N'dbo.prj_attribute_master_new_test', N'where_in_financial_statement') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_master_new_test ADD where_in_financial_statement nvarchar(255) NULL;';

    DECLARE @sql nvarchar(max);

    /* Backfill canonical definition from a legacy source when one existed. */
    IF @stg_definition_source IS NOT NULL AND @stg_definition_source <> N'prj_attribute_definition'
    BEGIN
        SET @sql = N'UPDATE stg.prj_attribute_master_new_test
                     SET prj_attribute_definition = COALESCE(prj_attribute_definition, ' + QUOTENAME(@stg_definition_source) + N');';
        EXEC sys.sp_executesql @sql;
    END;

    IF @dbo_definition_source IS NOT NULL AND @dbo_definition_source <> N'prj_attribute_definition'
    BEGIN
        SET @sql = N'UPDATE dbo.prj_attribute_master_new_test
                     SET prj_attribute_definition = COALESCE(prj_attribute_definition, ' + QUOTENAME(@dbo_definition_source) + N');';
        EXEC sys.sp_executesql @sql;
    END;

    /* Backfill canonical segment/financial-statement source from legacy segment. */
    IF @stg_segment_source IS NOT NULL AND @stg_segment_source <> N'where_in_financial_statement'
    BEGIN
        SET @sql = N'UPDATE stg.prj_attribute_master_new_test
                     SET where_in_financial_statement = CASE
                         WHEN where_in_financial_statement IS NULL OR LTRIM(RTRIM(where_in_financial_statement)) = N''''
                         THEN CONVERT(nvarchar(255), ' + QUOTENAME(@stg_segment_source) + N')
                         ELSE where_in_financial_statement END;';
        EXEC sys.sp_executesql @sql;
    END;

    IF @dbo_segment_source IS NOT NULL AND @dbo_segment_source <> N'where_in_financial_statement'
    BEGIN
        SET @sql = N'UPDATE dbo.prj_attribute_master_new_test
                     SET where_in_financial_statement = CASE
                         WHEN where_in_financial_statement IS NULL OR LTRIM(RTRIM(where_in_financial_statement)) = N''''
                         THEN CONVERT(nvarchar(255), ' + QUOTENAME(@dbo_segment_source) + N')
                         ELSE where_in_financial_statement END;';
        EXEC sys.sp_executesql @sql;
    END;

    EXEC sys.sp_executesql N'UPDATE stg.prj_attribute_master_new_test SET where_in_financial_statement=N''NA'' WHERE where_in_financial_statement IS NULL OR LTRIM(RTRIM(where_in_financial_statement))=N'''';';
    EXEC sys.sp_executesql N'UPDATE dbo.prj_attribute_master_new_test SET where_in_financial_statement=N''NA'' WHERE where_in_financial_statement IS NULL OR LTRIM(RTRIM(where_in_financial_statement))=N'''';';

    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'stg.prj_attribute_master_new_test') AND name=N'where_in_financial_statement' AND is_nullable=1)
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_master_new_test ALTER COLUMN where_in_financial_statement nvarchar(255) NOT NULL;';
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'dbo.prj_attribute_master_new_test') AND name=N'where_in_financial_statement' AND is_nullable=1)
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_master_new_test ALTER COLUMN where_in_financial_statement nvarchar(255) NOT NULL;';

    IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id=dc.parent_object_id AND c.column_id=dc.parent_column_id
        WHERE dc.parent_object_id=OBJECT_ID(N'stg.prj_attribute_master_new_test') AND c.name=N'where_in_financial_statement')
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_master_new_test ADD CONSTRAINT DF_stg_master_new_where_mig DEFAULT(N''NA'') FOR where_in_financial_statement;';

    IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id=dc.parent_object_id AND c.column_id=dc.parent_column_id
        WHERE dc.parent_object_id=OBJECT_ID(N'dbo.prj_attribute_master_new_test') AND c.name=N'where_in_financial_statement')
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_master_new_test ADD CONSTRAINT DF_master_new_where_mig DEFAULT(N''NA'') FOR where_in_financial_statement;';

    /* ----------------------------------------------------------------------
       2) Add scoped Definition + Segment to STAGING/FINAL business rules.
       ---------------------------------------------------------------------- */
    IF COL_LENGTH(N'stg.prj_attribute_business_rules_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD prj_attribute_definition nvarchar(max) NULL;';
    IF COL_LENGTH(N'stg.prj_attribute_business_rules_new_test', N'segment') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD segment nvarchar(255) NULL;';
    IF COL_LENGTH(N'dbo.prj_attribute_business_rules_new_test', N'prj_attribute_definition') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD prj_attribute_definition nvarchar(max) NULL;';
    IF COL_LENGTH(N'dbo.prj_attribute_business_rules_new_test', N'segment') IS NULL
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD segment nvarchar(255) NULL;';

    /* Backfill only after the target columns exist; dynamic SQL avoids batch compile errors. */
    SET @sql = N'
        UPDATE r
           SET r.prj_attribute_definition = COALESCE(r.prj_attribute_definition, m.prj_attribute_definition),
               r.segment = CASE
                   WHEN r.segment IS NULL OR LTRIM(RTRIM(r.segment))=N'''' OR r.segment=N''NA''
                   THEN COALESCE(CONVERT(nvarchar(255),m.where_in_financial_statement),N''NA'')
                   ELSE r.segment END
          FROM stg.prj_attribute_business_rules_new_test r
          JOIN stg.prj_attribute_master_new_test m ON m.prj_id=r.prj_id;';
    EXEC sys.sp_executesql @sql;

    SET @sql = N'
        UPDATE r
           SET r.prj_attribute_definition = COALESCE(r.prj_attribute_definition, m.prj_attribute_definition),
               r.segment = CASE
                   WHEN r.segment IS NULL OR LTRIM(RTRIM(r.segment))=N'''' OR r.segment=N''NA''
                   THEN COALESCE(CONVERT(nvarchar(255),m.where_in_financial_statement),N''NA'')
                   ELSE r.segment END
          FROM dbo.prj_attribute_business_rules_new_test r
          JOIN dbo.prj_attribute_master_new_test m ON m.prj_id=r.prj_id;';
    EXEC sys.sp_executesql @sql;

    EXEC sys.sp_executesql N'UPDATE stg.prj_attribute_business_rules_new_test SET segment=N''NA'' WHERE segment IS NULL OR LTRIM(RTRIM(segment))=N'''';';
    EXEC sys.sp_executesql N'UPDATE dbo.prj_attribute_business_rules_new_test SET segment=N''NA'' WHERE segment IS NULL OR LTRIM(RTRIM(segment))=N'''';';

    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'stg.prj_attribute_business_rules_new_test') AND name=N'segment' AND is_nullable=1)
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ALTER COLUMN segment nvarchar(255) NOT NULL;';
    IF EXISTS (SELECT 1 FROM sys.columns WHERE object_id=OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test') AND name=N'segment' AND is_nullable=1)
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ALTER COLUMN segment nvarchar(255) NOT NULL;';

    IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id=dc.parent_object_id AND c.column_id=dc.parent_column_id
        WHERE dc.parent_object_id=OBJECT_ID(N'stg.prj_attribute_business_rules_new_test') AND c.name=N'segment')
        EXEC sys.sp_executesql N'ALTER TABLE stg.prj_attribute_business_rules_new_test ADD CONSTRAINT DF_stg_rules_new_segment_mig DEFAULT(N''NA'') FOR segment;';

    IF NOT EXISTS (
        SELECT 1 FROM sys.default_constraints dc
        JOIN sys.columns c ON c.object_id=dc.parent_object_id AND c.column_id=dc.parent_column_id
        WHERE dc.parent_object_id=OBJECT_ID(N'dbo.prj_attribute_business_rules_new_test') AND c.name=N'segment')
        EXEC sys.sp_executesql N'ALTER TABLE dbo.prj_attribute_business_rules_new_test ADD CONSTRAINT DF_rules_new_segment_mig DEFAULT(N''NA'') FOR segment;';

    COMMIT TRANSACTION;

    SELECT N'Migration completed successfully' AS migration_result,
           COALESCE(@stg_definition_source,N'<none - new canonical column initialized>') AS staging_original_definition_source,
           COALESCE(@dbo_definition_source,N'<none - new canonical column initialized>') AS final_original_definition_source,
           COALESCE(@stg_segment_source,N'<none - defaulted to NA>') AS staging_original_segment_source,
           COALESCE(@dbo_segment_source,N'<none - defaulted to NA>') AS final_original_segment_source;
END TRY
BEGIN CATCH
    IF @@TRANCOUNT > 0 ROLLBACK TRANSACTION;
    THROW;
END CATCH;
