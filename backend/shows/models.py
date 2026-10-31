import os
import re
import uuid

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models.signals import post_delete
from django.dispatch import receiver
from django.utils.text import get_valid_filename

from .uploads import delete_stored


def production_logo_path(instance, filename):
    # A new name for each logo, so the old file can be deleted after the new
    # one is saved, and the name changes whenever the logo does.
    return f"productions/{instance.pk}/logo-{uuid.uuid4().hex}{os.path.splitext(filename)[1]}"


class Production(models.Model):
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="productions"
    )
    name = models.CharField(max_length=200)
    company = models.CharField(max_length=200, blank=True)
    venue = models.CharField(max_length=200, blank=True)
    # The run of the show: first and last performance. Either may be unknown.
    opening_date = models.DateField(null=True, blank=True)
    closing_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    # An optional PNG, JPEG, GIF or WebP, set through /productions/{id}/logo/.
    logo = models.FileField(upload_to=production_logo_path, blank=True, max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(closing_date__isnull=True)
                | models.Q(opening_date__isnull=True)
                | models.Q(closing_date__gte=models.F("opening_date")),
                name="closing_not_before_opening",
            ),
        ]

    def __str__(self):
        return self.name


@receiver(post_delete, sender=Production)
def delete_production_logo(sender, instance, **kwargs):
    delete_stored(instance.logo)


class EosConsole(models.Model):
    """An ETC Eos console this production follows over OSC (see ``console.py``).

    While it is enabled, the server listens and records each cue the console
    fires on the production's open run. Nothing is ever sent to the console.
    """

    class Transport(models.TextChoices):
        UDP = "udp", "UDP"
        TCP = "tcp", "TCP"

    class Framing(models.TextChoices):
        OSC_10 = "1.0", "OSC 1.0 (length headers)"
        OSC_11 = "1.1", "OSC 1.1 (SLIP)"

    production = models.OneToOneField(Production, on_delete=models.CASCADE, primary_key=True, related_name="eos_console")
    enabled = models.BooleanField(default=False)
    # UDP: the console sends to this server on ``port``. TCP: the server connects
    # to the console at ``host``:``port`` and reads.
    transport = models.CharField(max_length=3, choices=Transport.choices, default=Transport.UDP)
    port = models.PositiveIntegerField(default=4703, validators=[MinValueValidator(1), MaxValueValidator(65535)])
    host = models.CharField(max_length=255, blank=True)
    framing = models.CharField(max_length=3, choices=Framing.choices, default=Framing.OSC_10)
    cue_list = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            # Eos's messages don't say which show they're for, so a UDP port belongs to one production.
            models.UniqueConstraint(
                fields=["port"],
                condition=models.Q(enabled=True, transport="udp"),
                name="unique_enabled_udp_port",
            ),
        ]

    def __str__(self):
        return f"Eos console for {self.production}"


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


def normalize_follow(text):
    """Eos's "F2" or "H0.5" from what was typed. A bare number is a follow, and
    0 (or nothing) is neither, so most cues need nothing typed at all."""
    value = text.strip().upper()
    if value and value[0] not in "FH":
        value = "" if re.fullmatch(r"0+(\.0*)?", value) else f"F{value}"
    return value


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
    # When the record was made, which is not when the run happened.
    created_at = models.DateTimeField(auto_now_add=True)
    # The planned start ("curtain 19:30"), if one was set.
    scheduled_start = models.DateTimeField(null=True, blank=True)
    # The actual start and end. ``started_at`` is set by the first cue action
    # (not a hold) and ``ended_at`` by "End run"; operators can correct both.
    started_at = models.DateTimeField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        # Newest record first. Not by scheduled start: runs booked ahead of
        # time would then sit above the one being run tonight, and the board
        # opens the first run in this order.
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["production", "label"], name="unique_run_label"),
            models.CheckConstraint(
                condition=models.Q(ended_at__isnull=True)
                | models.Q(started_at__isnull=True)
                | models.Q(ended_at__gte=models.F("started_at")),
                name="run_ends_after_start",
            ),
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


class CueNote(models.Model):
    """A note about a cue in one run ("Q12 late"), apart from the cue's standing notes.

    Unlike the event log these can be edited and deleted: they are working
    notes, often written up after the run. The cue's number and label are
    copied when the note is made, as on events, so the note still says which
    cue it was about if the cue is renumbered or deleted.
    """

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="cue_notes")
    cue = models.ForeignKey(Cue, on_delete=models.SET_NULL, null=True, blank=True, related_name="run_notes")
    cue_number = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    cue_label = models.CharField(max_length=200, blank=True)
    text = models.TextField(max_length=2000)
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "id"]

    @property
    def production(self):
        return self.run.production

    def __str__(self):
        return f"{self.run.label}: Q{format_number(self.cue_number)} {self.text[:40]}"


def production_file_path(instance, filename):
    # A fresh folder per upload, so versions with the same name never collide
    # and a stored path says nothing about the next one.
    return f"productions/{instance.production_id}/files/{uuid.uuid4().hex}/{get_valid_filename(filename)}"


class ProductionFile(models.Model):
    """A script, showfile or other attachment on a production.

    Uploading a file with the same kind and name as an earlier one adds a new
    version and keeps the old ones. The stored file is deleted with the row,
    including when its production is deleted.
    """

    class Kind(models.TextChoices):
        # Scripts are PDFs; the board shows the latest one at the active cue's page.
        SCRIPT = "script"
        SHOWFILE = "showfile"
        OTHER = "other"

    production = models.ForeignKey(Production, on_delete=models.CASCADE, related_name="files")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.OTHER)
    # The name it was uploaded with; versions are grouped by kind and name.
    name = models.CharField(max_length=255)
    version = models.PositiveIntegerField()
    file = models.FileField(upload_to=production_file_path, max_length=500)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=100)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["kind", "name", "-version"]
        constraints = [
            models.UniqueConstraint(fields=["production", "kind", "name", "version"], name="unique_file_version"),
        ]

    def __str__(self):
        return f"{self.production}: {self.name} v{self.version}"


@receiver(post_delete, sender=ProductionFile)
def delete_production_file(sender, instance, **kwargs):
    delete_stored(instance.file)
