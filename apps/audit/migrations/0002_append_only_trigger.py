from django.db import migrations

# The audit trail is evidence: nobody, including the app's own DB role, may edit or delete
# entries. One exception: actor is ON DELETE SET NULL (keep the trail when a user account
# is removed), so the trigger allows an UPDATE whose only change is actor_id -> NULL.
FORWARD = """
CREATE OR REPLACE FUNCTION audit_reject_mutation() RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'UPDATE'
       AND NEW.actor_id IS NULL
       AND OLD.actor_id IS NOT NULL
       AND (NEW.id, NEW.action, NEW.entity_type, NEW.entity_id, NEW.metadata::text,
            NEW.ip_address, NEW.user_agent, NEW.created_at)
           IS NOT DISTINCT FROM
           (OLD.id, OLD.action, OLD.entity_type, OLD.entity_id, OLD.metadata::text,
            OLD.ip_address, OLD.user_agent, OLD.created_at)
    THEN
        RETURN NEW;  -- the FK's SET NULL when an actor is deleted
    END IF;
    RAISE EXCEPTION 'audit_auditlog is append-only (% rejected)', TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_append_only
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_reject_mutation();
"""

REVERSE = """
DROP TRIGGER IF EXISTS audit_append_only ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_reject_mutation();
"""


class Migration(migrations.Migration):
    dependencies = [("audit", "0001_initial")]

    operations = [migrations.RunSQL(FORWARD, REVERSE)]
