import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("shows", "0003_backfill_runs_and_numbers"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="cue",
            name="unique_cue_order",
        ),
        migrations.RemoveField(
            model_name="cue",
            name="order",
        ),
        migrations.RemoveField(
            model_name="cue",
            name="number",
        ),
        migrations.RenameField(
            model_name="cue",
            old_name="number_decimal",
            new_name="number",
        ),
        migrations.AlterField(
            model_name="cue",
            name="number",
            field=models.DecimalField(decimal_places=4, max_digits=10),
        ),
        migrations.AlterModelOptions(
            name="cue",
            options={"ordering": ["number"]},
        ),
        migrations.AddConstraint(
            model_name="cue",
            constraint=models.UniqueConstraint(fields=("production", "number"), name="unique_cue_number"),
        ),
        migrations.RemoveField(
            model_name="cueevent",
            name="run_label",
        ),
        migrations.AlterField(
            model_name="cueevent",
            name="run",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE, related_name="events", to="shows.run"
            ),
        ),
    ]
