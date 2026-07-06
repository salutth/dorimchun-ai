DO $$
DECLARE
  cname text;
BEGIN
  FOR cname IN
    SELECT constraint_name FROM information_schema.table_constraints
    WHERE table_name = 'species_observations' AND constraint_type = 'UNIQUE'
  LOOP
    EXECUTE 'ALTER TABLE species_observations DROP CONSTRAINT ' || cname;
  END LOOP;
END $$;
