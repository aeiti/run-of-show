from django.conf import settings
from django.db import models


class Production(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="productions"
    )
    name = models.CharField(max_length=200)
    venue = models.CharField(max_length=200, blank=True)
    performance_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Cue(models.Model):
    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="cues")
    # Char, not int: stage managers use numbers like "102" and "102.5".
    number = models.CharField(max_length=20)
    label = models.CharField(max_length=200, blank=True)
    page = models.PositiveIntegerField(null=True, blank=True)
    order = models.PositiveIntegerField()

    class Meta:
        ordering = ["order", "id"]
        constraints = [
            models.UniqueConstraint(fields=["production", "order"], name="unique_cue_order"),
        ]

    def __str__(self):
        return f"Q{self.number} {self.label}".strip()


class AppendOnlyError(Exception):
    pass


class CueEvent(models.Model):
    """One firing of a cue during a run. Insert-only.

    Enforced in the app layer only: saving an existing row or deleting an
    instance raises. The database itself does not block UPDATE/DELETE, and
    deleting a cue or production cascades through its events.
    """

    cue = models.ForeignKey(Cue, on_delete=models.CASCADE, related_name="events")
    run_label = models.CharField(max_length=100)
    fired_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        ordering = ["fired_at", "id"]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise AppendOnlyError("CueEvent rows are insert-only.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise AppendOnlyError("CueEvent rows are insert-only.")

    def __str__(self):
        return f"{self.run_label}: {self.cue} @ {self.fired_at:%H:%M:%S}"
