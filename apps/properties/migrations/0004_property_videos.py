from django.contrib.postgres.fields import ArrayField
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("properties", "0003_propertytenantrequest"),
    ]

    operations = [
        migrations.AddField(
            model_name="property",
            name="videos",
            field=ArrayField(
                base_field=models.URLField(max_length=500),
                blank=True,
                default=list,
                size=10,
            ),
        ),
    ]