/* PostgreSQL existing-database alignment for the portfolio reference.
   Canonical PostgreSQL table: prj_dbd.prj_portfolio_reference
   SQL Server is not affected by this script.

   Safe/idempotent behavior:
   - Requires the canonical portfolio table and both business-rule tables.
   - Repoints only FK constraints involving port_ref_id.
   - Does not delete or modify application data.
*/
BEGIN;

DO $$
BEGIN
  IF to_regclass('prj_dbd.prj_portfolio_reference') IS NULL THEN
    RAISE EXCEPTION 'Required table prj_dbd.prj_portfolio_reference does not exist.';
  END IF;
  IF to_regclass('prj_stage.prj_attribute_business_rules_new_test') IS NULL THEN
    RAISE EXCEPTION 'Required table prj_stage.prj_attribute_business_rules_new_test does not exist.';
  END IF;
  IF to_regclass('prj_dbd.prj_attribute_business_rules_new_test') IS NULL THEN
    RAISE EXCEPTION 'Required table prj_dbd.prj_attribute_business_rules_new_test does not exist.';
  END IF;
END $$;

DO $$
DECLARE
  rec record;
BEGIN
  FOR rec IN
    SELECT n.nspname AS schema_name, t.relname AS table_name, c.conname AS constraint_name
    FROM pg_constraint c
    JOIN pg_class t ON t.oid = c.conrelid
    JOIN pg_namespace n ON n.oid = t.relnamespace
    WHERE c.contype = 'f'
      AND (
        (n.nspname = 'prj_stage' AND t.relname = 'prj_attribute_business_rules_new_test') OR
        (n.nspname = 'prj_dbd' AND t.relname = 'prj_attribute_business_rules_new_test')
      )
      AND EXISTS (
        SELECT 1
        FROM unnest(c.conkey) AS key_col(attnum)
        JOIN pg_attribute a
          ON a.attrelid = t.oid
         AND a.attnum = key_col.attnum
        WHERE a.attname = 'port_ref_id'
      )
  LOOP
    EXECUTE format('ALTER TABLE %I.%I DROP CONSTRAINT %I', rec.schema_name, rec.table_name, rec.constraint_name);
  END LOOP;
END $$;

ALTER TABLE prj_stage.prj_attribute_business_rules_new_test
  ADD CONSTRAINT fk_stg_rules_portfolio_reference
  FOREIGN KEY (port_ref_id)
  REFERENCES prj_dbd.prj_portfolio_reference(port_ref_id);

ALTER TABLE prj_dbd.prj_attribute_business_rules_new_test
  ADD CONSTRAINT fk_rules_portfolio_reference
  FOREIGN KEY (port_ref_id)
  REFERENCES prj_dbd.prj_portfolio_reference(port_ref_id);

COMMIT;
