from django.db import migrations, models


class Migration(migrations.Migration):
    """Opening and closing dates for a production; planned and actual start for a run.

    ``performance_date`` is copied to ``opening_date`` and dropped in 0012.
    """

    dependencies = [
        ("shows", "0010_production_logo"),
    ]

    operations = [
        migrations.AddField(
            model_name="production",
            name="opening_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="production",
            name="closing_date",
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="scheduled_start",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="run",
            name="started_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
