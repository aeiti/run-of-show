import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Additive half of the v1 schema change. 0003 moves the data, 0004 drops the old columns."""

    dependencies = [
        ("shows", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="production",
            name="company",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="production",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="cue",
            name="notes",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="cue",
            name="scene",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name="cue",
            name="number_decimal",
            field=models.DecimalField(decimal_places=4, max_digits=10, null=True),
        ),
        migrations.CreateModel(
            name="Run",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("label", models.CharField(max_length=100)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("rehearsal", "Rehearsal"),
                            ("tech", "Tech"),
                            ("preview", "Preview"),
                            ("performance", "Performance"),
                            ("other", "Other"),
                        ],
                        default="other",
                        max_length=20,
                    ),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("ended_at", models.DateTimeField(blank=True, null=True)),
                ("notes", models.TextField(blank=True)),
                (
                    "production",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="runs", to="shows.production"
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "constraints": [
                    models.UniqueConstraint(fields=("production", "label"), name="unique_run_label"),
                ],
            },
        ),
        migrations.AddField(
            model_name="cueevent",
            name="run",
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.CASCADE, related_name="events", to="shows.run"
            ),
        ),
        migrations.AddField(
            model_name="cueevent",
            name="action",
            field=models.CharField(
                choices=[("go", "Go"), ("back", "Back"), ("goto", "Goto"), ("reset", "Reset")],
                default="go",
                max_length=10,
            ),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name="cueevent",
            name="cue_number",
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="cueevent",
            name="cue_label",
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AlterField(
            model_name="cueevent",
            name="cue",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="events",
                to="shows.cue",
            ),
        ),
    ]
