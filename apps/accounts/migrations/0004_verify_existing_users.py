from django.db import migrations
from django.db.models.functions import Now


def mark_existing_users_verified(apps, schema_editor):
    """
    Accounts created before email verification existed were never sent a link. Treating
    them as verified avoids locking every existing user out the moment this ships; only
    accounts registered from now on must verify.
    """
    User = apps.get_model("accounts", "User")
    User.objects.filter(email_verified_at__isnull=True).update(email_verified_at=Now())


class Migration(migrations.Migration):
    dependencies = [("accounts", "0003_email_verified_at")]

    operations = [migrations.RunPython(mark_existing_users_verified, migrations.RunPython.noop)]
