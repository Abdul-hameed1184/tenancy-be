from django.db import migrations

# Row-level trigger: any UPDATE or DELETE on the ledger raises, whoever issues it (ORM, raw
# SQL, admin, a psql session). TRUNCATE doesn't fire row triggers, which is what lets the
# test runner reset the table between tests.
FORWARD = """
CREATE OR REPLACE FUNCTION payments_reject_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'payments_paymententry is append-only (% rejected)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER payments_append_only
    BEFORE UPDATE OR DELETE ON payments_paymententry
    FOR EACH ROW EXECUTE FUNCTION payments_reject_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS payments_append_only ON payments_paymententry;
DROP FUNCTION IF EXISTS payments_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("payments", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
