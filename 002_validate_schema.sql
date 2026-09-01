/* PostgreSQL schema validator for the business/display split.
   Read-only. Required physical schemas: prj_stage + prj_dbd. */
DO $$
DECLARE
  rec record;
  missing text := '';
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='prj_stage') THEN
    missing := missing || E'\nMissing schema prj_stage';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name='prj_dbd') THEN
    missing := missing || E'\nMissing schema prj_dbd';
  END IF;

  FOR rec IN
    SELECT * FROM (VALUES
      ('prj_dbd','raw_prj_attribute_new_test','raw_row_id'),
      ('prj_dbd','raw_prj_attribute_new_test','portfolio'),
      ('prj_dbd','raw_prj_attribute_new_test','prj_id'),
      ('prj_dbd','raw_prj_attribute_new_test','prj_attribute_name'),
      ('prj_dbd','raw_prj_attribute_new_test','prj_physical_attribute_name'),
      ('prj_dbd','raw_prj_attribute_new_test','section'),
      ('prj_dbd','raw_prj_attribute_new_test','sub_section'),
      ('prj_dbd','raw_prj_attribute_new_test','data_type'),
      ('prj_dbd','raw_prj_attribute_new_test','calculated_or_reported'),
      ('prj_dbd','raw_prj_attribute_new_test','calculation_logic'),
      ('prj_dbd','raw_prj_attribute_new_test','segment'),
      ('prj_dbd','raw_prj_attribute_new_test','report_type'),
      ('prj_dbd','raw_prj_attribute_new_test','attribute_definition'),
      ('prj_dbd','raw_prj_attribute_new_test','attribute_description'),
      ('prj_dbd','raw_prj_attribute_new_test','display_order'),
      ('prj_dbd','raw_prj_attribute_new_test','tech_logic'),
      ('prj_dbd','raw_prj_attribute_new_test','display_name'),
      ('prj_dbd','raw_prj_attribute_new_test','is_active'),
      ('prj_dbd','raw_prj_attribute_new_test','created_at'),
      ('prj_dbd','raw_prj_attribute_new_test','updated_at'),
      ('prj_dbd','raw_prj_attribute_new_test','created_by'),
      ('prj_dbd','raw_prj_attribute_new_test','updated_by'),

      ('prj_dbd','prj_portfolio_reference','port_ref_id'),
      ('prj_dbd','prj_portfolio_reference','portfolio_name'),
      ('prj_dbd','prj_portfolio_reference','sector_name'),
      ('prj_dbd','prj_portfolio_reference','sub_sector'),
      ('prj_dbd','prj_portfolio_reference','remark'),
      ('prj_dbd','prj_portfolio_reference','is_active'),
      ('prj_dbd','prj_portfolio_reference','created_at'),
      ('prj_dbd','prj_portfolio_reference','updated_at'),
      ('prj_dbd','prj_portfolio_reference','created_by'),
      ('prj_dbd','prj_portfolio_reference','updated_by'),

      ('prj_stage','prj_attribute_master_new_test','prj_id'),
      ('prj_stage','prj_attribute_master_new_test','prj_attribute_name'),
      ('prj_stage','prj_attribute_master_new_test','prj_attribute_definition'),
      ('prj_stage','prj_attribute_master_new_test','prj_physical_attribute_name'),
      ('prj_stage','prj_attribute_master_new_test','where_in_financial_statement'),
      ('prj_stage','prj_attribute_master_new_test','is_active'),
      ('prj_stage','prj_attribute_master_new_test','created_at'),
      ('prj_stage','prj_attribute_master_new_test','updated_at'),
      ('prj_stage','prj_attribute_master_new_test','created_by'),
      ('prj_stage','prj_attribute_master_new_test','updated_by'),

      ('prj_dbd','prj_attribute_master_new_test','prj_id'),
      ('prj_dbd','prj_attribute_master_new_test','prj_attribute_name'),
      ('prj_dbd','prj_attribute_master_new_test','prj_attribute_definition'),
      ('prj_dbd','prj_attribute_master_new_test','prj_physical_attribute_name'),
      ('prj_dbd','prj_attribute_master_new_test','where_in_financial_statement'),
      ('prj_dbd','prj_attribute_master_new_test','is_active'),
      ('prj_dbd','prj_attribute_master_new_test','created_at'),
      ('prj_dbd','prj_attribute_master_new_test','updated_at'),
      ('prj_dbd','prj_attribute_master_new_test','created_by'),
      ('prj_dbd','prj_attribute_master_new_test','updated_by'),

      ('prj_stage','prj_attribute_business_rules_new_test','scope_id'),
      ('prj_stage','prj_attribute_business_rules_new_test','prj_id'),
      ('prj_stage','prj_attribute_business_rules_new_test','port_ref_id'),
      ('prj_stage','prj_attribute_business_rules_new_test','source_abbr_name'),
      ('prj_stage','prj_attribute_business_rules_new_test','prompt_description'),
      ('prj_stage','prj_attribute_business_rules_new_test','examples_for_llm'),
      ('prj_stage','prj_attribute_business_rules_new_test','editable'),
      ('prj_stage','prj_attribute_business_rules_new_test','data_type'),
      ('prj_stage','prj_attribute_business_rules_new_test','attribute_type'),
      ('prj_stage','prj_attribute_business_rules_new_test','business_logic'),
      ('prj_stage','prj_attribute_business_rules_new_test','calculation_logic'),
      ('prj_stage','prj_attribute_business_rules_new_test','created_at'),
      ('prj_stage','prj_attribute_business_rules_new_test','updated_at'),
      ('prj_stage','prj_attribute_business_rules_new_test','created_by'),
      ('prj_stage','prj_attribute_business_rules_new_test','updated_by'),

      ('prj_dbd','prj_attribute_business_rules_new_test','scope_id'),
      ('prj_dbd','prj_attribute_business_rules_new_test','prj_id'),
      ('prj_dbd','prj_attribute_business_rules_new_test','port_ref_id'),
      ('prj_dbd','prj_attribute_business_rules_new_test','source_abbr_name'),
      ('prj_dbd','prj_attribute_business_rules_new_test','prompt_description'),
      ('prj_dbd','prj_attribute_business_rules_new_test','examples_for_llm'),
      ('prj_dbd','prj_attribute_business_rules_new_test','editable'),
      ('prj_dbd','prj_attribute_business_rules_new_test','data_type'),
      ('prj_dbd','prj_attribute_business_rules_new_test','attribute_type'),
      ('prj_dbd','prj_attribute_business_rules_new_test','business_logic'),
      ('prj_dbd','prj_attribute_business_rules_new_test','calculation_logic'),
      ('prj_dbd','prj_attribute_business_rules_new_test','created_at'),
      ('prj_dbd','prj_attribute_business_rules_new_test','updated_at'),
      ('prj_dbd','prj_attribute_business_rules_new_test','created_by'),
      ('prj_dbd','prj_attribute_business_rules_new_test','updated_by'),

      ('prj_stage','prj_attribute_display_test','display_id'),
      ('prj_stage','prj_attribute_display_test','scope_id'),
      ('prj_stage','prj_attribute_display_test','display_order'),
      ('prj_stage','prj_attribute_display_test','prj_id'),
      ('prj_stage','prj_attribute_display_test','display_name'),
      ('prj_stage','prj_attribute_display_test','section'),
      ('prj_stage','prj_attribute_display_test','subsection'),
      ('prj_stage','prj_attribute_display_test','prj_attribute_definition'),
      ('prj_stage','prj_attribute_display_test','prj_attribute_description'),
      ('prj_stage','prj_attribute_display_test','segment'),
      ('prj_stage','prj_attribute_display_test','report_type'),
      ('prj_stage','prj_attribute_display_test','created_at'),
      ('prj_stage','prj_attribute_display_test','updated_at'),
      ('prj_stage','prj_attribute_display_test','created_by'),
      ('prj_stage','prj_attribute_display_test','updated_by'),

      ('prj_dbd','prj_attribute_display_test','display_id'),
      ('prj_dbd','prj_attribute_display_test','scope_id'),
      ('prj_dbd','prj_attribute_display_test','display_order'),
      ('prj_dbd','prj_attribute_display_test','prj_id'),
      ('prj_dbd','prj_attribute_display_test','display_name'),
      ('prj_dbd','prj_attribute_display_test','section'),
      ('prj_dbd','prj_attribute_display_test','subsection'),
      ('prj_dbd','prj_attribute_display_test','prj_attribute_definition'),
      ('prj_dbd','prj_attribute_display_test','prj_attribute_description'),
      ('prj_dbd','prj_attribute_display_test','segment'),
      ('prj_dbd','prj_attribute_display_test','report_type'),
      ('prj_dbd','prj_attribute_display_test','created_at'),
      ('prj_dbd','prj_attribute_display_test','updated_at'),
      ('prj_dbd','prj_attribute_display_test','created_by'),
      ('prj_dbd','prj_attribute_display_test','updated_by'),

      ('prj_dbd','audit_table_new_test','audit_id'),
      ('prj_dbd','audit_table_new_test','schema_name'),
      ('prj_dbd','audit_table_new_test','table_name'),
      ('prj_dbd','audit_table_new_test','record_key'),
      ('prj_dbd','audit_table_new_test','action'),
      ('prj_dbd','audit_table_new_test','before_value'),
      ('prj_dbd','audit_table_new_test','after_value'),
      ('prj_dbd','audit_table_new_test','source_operation'),
      ('prj_dbd','audit_table_new_test','performed_by'),
      ('prj_dbd','audit_table_new_test','performed_at')
    ) AS x(schema_name, table_name, column_name)
  LOOP
    IF NOT EXISTS (
      SELECT 1 FROM information_schema.columns c
      WHERE c.table_schema=rec.schema_name
        AND c.table_name=rec.table_name
        AND c.column_name=rec.column_name
    ) THEN
      missing := missing || format(E'\nMissing %I.%I.%I', rec.schema_name, rec.table_name, rec.column_name);
    END IF;
  END LOOP;

  IF to_regclass('prj_dbd.prj_data_sources') IS NULL AND to_regclass('prj_dbd.prj_data_source') IS NULL THEN
    missing := missing || E'\nMissing read-only dependency prj_dbd.prj_data_sources (or singular prj_data_source)';
  END IF;

  IF missing <> '' THEN
    RAISE EXCEPTION 'Schema validation failed:%', missing;
  END IF;
END $$;

SELECT 'Schema validation passed' AS validation_status, 0 AS missing_count;
