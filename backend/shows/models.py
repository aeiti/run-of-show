from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models


class Production(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="productions"
    )
    name = models.CharField(max_length=200)
    company = models.CharField(max_length=200, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    performance_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    """Someone other than the owner who works on a production, and in what role.

    The owner is not a member: ``Production.owner`` is the one person who can
    delete the production. What each role may do is in ``access.py``.
    """

    class Role(models.TextChoices):
        STAGE_MANAGER = "stage_manager", "Stage manager"
        OPERATOR = "operator", "Operator"
        VIEWER = "viewer", "Viewer"

    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.VIEWER)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.UniqueConstraint(fields=["production", "user"], name="unique_membership"),
        ]

    def __str__(self):
        return f"{self.user} on {self.production} ({self.role})"


FOLLOW_VALIDATOR = RegexValidator(
    r"^[FH]\d{1,5}(\.\d{1,2})?$", "Follow is F or H and a time in seconds, such as F2 or H0.5."
)


class Cue(models.Model):
    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="cues")
    # Decimal so point cues sort where they belong: 12 < 12.5 < 13 < 100.
    number = models.DecimalField(max_digits=10, decimal_places=4)
    label = models.CharField(max_length=200, blank=True)
    page = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # Eos "scene" text: the cue that starts a scene carries its name.
    scene = models.CharField(max_length=200, blank=True)
    # Cue timing in seconds, as on Eos. ``time`` is the up time and
    # ``down_time`` the down time when it differs. ``duration`` is Eos's own
    # total for the cue, which also counts delays, discrete times and parts;
    # it is cleared when the times are edited here, since it can't be
    # recomputed without them. ``follow`` is Eos's "F2" (follow) or "H3" (hang):
    # shown to the operator, never fired by the board.
    time = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    down_time = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    duration = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    follow = models.CharField(max_length=12, blank=True, validators=[FOLLOW_VALIDATOR])

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["production", "number"], name="unique_cue_number"),
        ]

    def __str__(self):
        return f"Q{format_number(self.number)} {self.label}".strip()


def format_number(number):
    """12.5000 -> "12.5", 100.0000 -> "100" (never "1E+2")."""
    if number is None:
        return None
    return format(number.normalize(), "f")


class Run(models.Model):
    class Kind(models.TextChoices):
        REHEARSAL = "rehearsal"
        TECH = "tech"
        PREVIEW = "preview"
        PERFORMANCE = "performance"
        OTHER = "other"

    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="runs")
    label = models.CharField(max_length=100)
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["production", "label"], name="unique_run_label"),
        ]

    def __str__(self):
        return f"{self.production}: {self.label}"


class AppendOnlyError(Exception):
    pass


class CueEvent(models.Model):
    """One operator action during a run. Insert-only.

    Enforced in the app layer only: saving an existing row or deleting an
    instance raises. The database itself does not block UPDATE/DELETE, and
    deleting a run or production cascades through its events.

    The cue's number and label are copied at the moment of the action, so
    editing or deleting the cue later does not rewrite the log.
    """

    class Action(models.TextChoices):
        GO = "go"
        BACK = "back"
        GOTO = "goto"
        RESET = "reset"
        # A hold pauses the run (``note`` says why) until a resume. Both
        # record the cue that was active, but never change it.
        HOLD = "hold"
        RESUME = "resume"

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="events")
    action = models.CharField(max_length=10, choices=Action.choices)
    # The cue that became active (for a hold or resume, the cue that was
    # active); null after a reset or if the cue was deleted.
    cue = models.ForeignKey(Cue, on_delete=models.SET_NULL, null=True, blank=True, related_name="events")
    cue_number = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    cue_label = models.CharField(max_length=200, blank=True)
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
        return f"{self.run.label}: {self.action} Q{format_number(self.cue_number)} @ {self.fired_at:%H:%M:%S}"
