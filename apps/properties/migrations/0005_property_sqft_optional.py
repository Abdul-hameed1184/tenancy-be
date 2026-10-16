from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0004_property_videos"),
    ]

    operations = [
        migrations.AlterField(
            model_name="property",
            name="sqft",
            field=models.PositiveIntegerField(blank=True, default=None, null=True),
        ),
    ]