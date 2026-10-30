import base64
import binascii
import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Q
from rest_framework import serializers

from accounts.models import display_name

from .access import role_for
from . import uploads
from .models import (
    FOLLOW_VALIDATOR,
    Cue,
    CueEvent,
    CueNote,
    Membership,
    Production,
    ProductionFile,
    Run,
    format_number,
)
from .services import run_state


class CueNumberField(serializers.DecimalField):
    """Accepts "12.5" or 12.5; returns "12.5" rather than "12.5000"."""

    def __init__(self, **kwargs):
        super().__init__(max_digits=10, decimal_places=4, **kwargs)

    def to_internal_value(self, data):
        value = super().to_internal_value(data)
        if value <= 0:
            raise serializers.ValidationError("Cue numbers must be greater than 0.")
        return value

    def to_representation(self, value):
        return format_number(value)


class SecondsField(serializers.DecimalField):
    """Cue times in seconds: 0 or more, returned as "3.9" rather than "3.90"."""

    def __init__(self, **kwargs):
        super().__init__(max_digits=8, decimal_places=2, min_value=0, allow_null=True, required=False, **kwargs)

    def to_representation(self, value):
        return format_number(value)


class PersonSerializer(serializers.Serializer):
    """Another user as collaborators see them: no email."""

    id = serializers.IntegerField()
    username = serializers.CharField()
    display_name = serializers.SerializerMethodField()

    def get_display_name(self, user):
        return display_name(user)


class ProductionSerializer(serializers.ModelSerializer):
    owner = PersonSerializer(read_only=True)
    # The requesting user's role, so the UI can show only what they may do.
    role = serializers.SerializerMethodField()
    # Null, or a token that changes whenever the logo does. The image itself
    # is private, so it is fetched from /productions/{id}/logo/.
    logo = serializers.SerializerMethodField()

    class Meta:
        model = Production
        fields = ["id", "name", "company", "venue", "performance_date", "notes", "logo", "created_at", "owner", "role"]
        read_only_fields = ["id", "created_at"]

    def get_role(self, production):
        return role_for(production, self.context["request"].user)

    def get_logo(self, production):
        return os.path.basename(production.logo.name) if production.logo else None


def check_logo(head, size):
    """(content type, extension) of an acceptable logo, from its size and first bytes."""
    limit = settings.PRODUCTION_LOGO_MAX_SIZE
    if size > limit:
        raise serializers.ValidationError(f"A logo can be up to {megabytes(limit)} MB.")
    image = uploads.image_type(head)
    if image is None:
        raise serializers.ValidationError("A logo must be a PNG, JPEG, GIF or WebP image.")
    return image


class LogoUploadSerializer(serializers.Serializer):
    file = serializers.FileField()

    def validate(self, data):
        try:
            data["content_type"], data["ext"] = check_logo(uploads.read_head(data["file"]), data["file"].size)
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"file": e.detail})
        return data


class MembershipSerializer(serializers.ModelSerializer):
    user = PersonSerializer(read_only=True)

    class Meta:
        model = Membership
        fields = ["id", "user", "role", "created_at"]
        read_only_fields = ["id", "user", "created_at"]


class InviteSerializer(serializers.Serializer):
    """Add an existing account to a production, found by username or email."""

    user = serializers.CharField()
    role = serializers.ChoiceField(Membership.Role.choices, default=Membership.Role.VIEWER)

    def validate_user(self, value):
        value = value.strip()
        users = get_user_model().objects.filter(Q(username__iexact=value) | Q(email__iexact=value), is_active=True)
        # Two accounts could share an email only if one predates the unique
        # check at sign-up; don't guess between them.
        if users.count() != 1:
            raise serializers.ValidationError("No single account has that username or email.")
        user = users.get()
        production = self.context["production"]
        if user.pk == production.owner_id:
            raise serializers.ValidationError(f"{user.username} owns this production.")
        if production.memberships.filter(user=user).exists():
            raise serializers.ValidationError(f"{user.username} is already on this production.")
        return user


class CueSerializer(serializers.ModelSerializer):
    number = CueNumberField()
    time = SecondsField()
    down_time = SecondsField()
    duration = SecondsField()
    # Declared here so "f2" can be upper-cased before the model's validator sees it.
    follow = serializers.CharField(max_length=12, allow_blank=True, required=False)

    TIMES = ("time", "down_time")

    class Meta:
        model = Cue
        fields = ["id", "number", "label", "page", "notes", "scene", "time", "down_time", "duration", "follow"]
        read_only_fields = ["id"]

    def validate_follow(self, value):
        value = value.strip().upper()
        if value:
            try:
                FOLLOW_VALIDATOR(value)
            except DjangoValidationError as e:
                raise serializers.ValidationError(e.messages)
        return value

    def update(self, instance, validated_data):
        # Eos's duration counts delays and discrete times this app doesn't
        # store, so once the times are edited here it no longer applies.
        edited = any(f in validated_data and validated_data[f] != getattr(instance, f) for f in self.TIMES)
        if edited and "duration" not in validated_data:
            validated_data["duration"] = None
        return super().update(instance, validated_data)

    def validate_number(self, value):
        production = self.context.get("production") or getattr(self.instance, "production", None)
        clash = Cue.objects.filter(production=production, number=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f"Cue {format_number(value)} already exists.")
        return value


class CueEventSerializer(serializers.ModelSerializer):
    cue_number = CueNumberField(read_only=True)

    class Meta:
        model = CueEvent
        fields = ["id", "run", "action", "cue", "cue_number", "cue_label", "fired_at", "note"]
        read_only_fields = fields


class RunSerializer(serializers.ModelSerializer):
    class Meta:
        model = Run
        fields = ["id", "production", "label", "kind", "created_at", "ended_at", "notes"]
        read_only_fields = ["id", "production", "created_at", "ended_at"]

    def validate_label(self, value):
        production = self.context.get("production") or getattr(self.instance, "production", None)
        clash = Run.objects.filter(production=production, label=value)
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(f"A run called {value!r} already exists.")
        return value


class HoldStateSerializer(serializers.Serializer):
    since = serializers.DateTimeField()
    reason = serializers.CharField()


class RunStateSerializer(serializers.Serializer):
    active_cue = serializers.IntegerField(allow_null=True)
    active_number = CueNumberField(allow_null=True)
    next_cue = serializers.IntegerField(allow_null=True)
    hold = HoldStateSerializer(allow_null=True)


class CueNoteSerializer(serializers.ModelSerializer):
    """A cue note in a run. The cue is set when the note is made; after that only the text changes."""

    cue_number = CueNumberField(read_only=True)
    author = serializers.SerializerMethodField()

    class Meta:
        model = CueNote
        fields = ["id", "run", "cue", "cue_number", "cue_label", "text", "author", "created_at", "updated_at"]
        read_only_fields = ["id", "run", "cue_number", "cue_label", "created_at", "updated_at"]
        extra_kwargs = {"cue": {"required": True, "allow_null": False}}

    def get_author(self, note):
        return (display_name(note.author) or note.author.get_username()) if note.author else ""

    def validate_cue(self, cue):
        if self.instance is not None and cue != self.instance.cue:
            raise serializers.ValidationError("A note's cue can't be changed. Delete it and add a new one.")
        run = self.context.get("run") or self.instance.run
        if cue.production_id != run.production_id:
            raise serializers.ValidationError("That cue is not in this production.")
        return cue

    def create(self, validated_data):
        cue = validated_data["cue"]
        return super().create({**validated_data, "cue_number": cue.number, "cue_label": cue.label})


class RunDetailSerializer(RunSerializer):
    events = CueEventSerializer(many=True, read_only=True)
    cue_notes = CueNoteSerializer(many=True, read_only=True)
    state = serializers.SerializerMethodField()

    class Meta(RunSerializer.Meta):
        fields = RunSerializer.Meta.fields + ["events", "cue_notes", "state"]

    def get_state(self, run):
        return RunStateSerializer(run_state(run)).data


class ProductionFileSerializer(serializers.ModelSerializer):
    uploaded_by = serializers.SerializerMethodField()

    class Meta:
        model = ProductionFile
        fields = ["id", "production", "kind", "name", "version", "size", "content_type", "uploaded_by", "uploaded_at"]
        read_only_fields = fields

    def get_uploaded_by(self, f):
        return (display_name(f.uploaded_by) or f.uploaded_by.get_username()) if f.uploaded_by else ""


class FileUploadSerializer(serializers.Serializer):
    """A new file, or a new version of one: same kind and name as an earlier upload."""

    file = serializers.FileField(max_length=255)
    kind = serializers.ChoiceField(ProductionFile.Kind.choices, default=ProductionFile.Kind.OTHER)

    def validate(self, data):
        upload = data["file"]
        limit = settings.PRODUCTION_FILE_MAX_SIZE
        if upload.size > limit:
            raise serializers.ValidationError({"file": f"Files can be up to {megabytes(limit)} MB."})
        if data["kind"] == ProductionFile.Kind.SCRIPT and not uploads.is_pdf(uploads.read_head(upload)):
            raise serializers.ValidationError({"file": "A script must be a PDF."})
        # Browsers send a bare name, but don't keep a path if one is sent.
        data["name"] = os.path.basename(upload.name).strip() or "file"
        return data


def megabytes(size):
    return format(size / (1024 * 1024), "g")


class CueTargetSerializer(serializers.Serializer):
    cue = serializers.IntegerField()


class HoldSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500)


class OptionalCueTargetSerializer(serializers.Serializer):
    cue = serializers.IntegerField(required=False, allow_null=True)


# Whole-production backup (see backup.py). The same serializers write the
# file and read it back, so an export always imports.

BACKUP_FORMAT = "run-of-show/production"
BACKUP_VERSION = 1


class BackupProductionSerializer(serializers.ModelSerializer):
    # Not a ProductionSerializer subclass: its owner and role belong to whoever
    # is asking, not to the production file.
    class Meta:
        model = Production
        fields = ["name", "company", "venue", "performance_date", "notes"]


class BackupCueSerializer(CueSerializer):
    class Meta(CueSerializer.Meta):
        fields = [f for f in CueSerializer.Meta.fields if f != "id"]

    def validate_number(self, value):
        # Clashes are checked across the whole file in BackupSerializer.
        return value


class BackupEventSerializer(serializers.ModelSerializer):
    # ``cue`` is the cue this event is still linked to, by its current
    # number; ``cue_number`` is the snapshot taken when the action happened.
    # They differ once a cue is renumbered, and ``cue`` is null once it is
    # deleted.
    cue = CueNumberField(source="cue.number", allow_null=True, required=False)
    cue_number = CueNumberField(allow_null=True, required=False)
    fired_at = serializers.DateTimeField()

    class Meta:
        model = CueEvent
        fields = ["action", "cue", "cue_number", "cue_label", "fired_at", "note"]


class BackupCueNoteSerializer(serializers.ModelSerializer):
    # ``cue`` and ``cue_number`` as on events. The author isn't kept: the
    # file may be imported where that user doesn't exist.
    cue = CueNumberField(source="cue.number", allow_null=True, required=False)
    cue_number = CueNumberField(allow_null=True, required=False)
    created_at = serializers.DateTimeField()
    updated_at = serializers.DateTimeField(required=False)

    class Meta:
        model = CueNote
        fields = ["cue", "cue_number", "cue_label", "text", "created_at", "updated_at"]


class BackupRunSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField()
    events = BackupEventSerializer(many=True, required=False)
    cue_notes = BackupCueNoteSerializer(many=True, required=False)

    class Meta:
        model = Run
        fields = ["label", "kind", "created_at", "ended_at", "notes", "events", "cue_notes"]


class BackupLogoSerializer(serializers.Serializer):
    """The logo inline as base64. Its type is read from the image, not from ``content_type``."""

    content_type = serializers.CharField(required=False)
    data = serializers.CharField()

    def validate_data(self, value):
        try:
            image = base64.b64decode(value, validate=True)
        except binascii.Error:
            raise serializers.ValidationError("The logo is not valid base64.")
        check_logo(image[:16], len(image))
        return image


class BackupSerializer(serializers.Serializer):
    format = serializers.CharField()
    version = serializers.IntegerField()
    exported_at = serializers.DateTimeField(required=False)
    production = BackupProductionSerializer()
    # Added after version 1 without a bump: a file without it still imports,
    # and an older app ignores it.
    logo = BackupLogoSerializer(required=False, allow_null=True)
    cues = BackupCueSerializer(many=True, required=False)
    runs = BackupRunSerializer(many=True, required=False)

    def to_internal_value(self, data):
        # Checked before the fields, as one plain message: the rest of a file
        # that isn't ours, or is from a newer app, would only add noise.
        if not isinstance(data, dict) or data.get("format") != BACKUP_FORMAT:
            raise serializers.ValidationError({"detail": "This is not a Run of Show production file."})
        version = data.get("version")
        if not isinstance(version, int) or not 1 <= version <= BACKUP_VERSION:
            raise serializers.ValidationError({"detail": f"Version {version} files need a newer version of Run of Show."})
        return super().to_internal_value(data)

    def validate_cues(self, cues):
        repeated = repeats(c["number"] for c in cues)
        if repeated:
            raise serializers.ValidationError(f"Cue {format_number(repeated)} appears more than once.")
        return cues

    def validate_runs(self, runs):
        repeated = repeats(r["label"] for r in runs)
        if repeated:
            raise serializers.ValidationError(f"A run called {repeated!r} appears more than once.")
        return runs

    def validate(self, data):
        numbers = {c["number"] for c in data.get("cues", [])}
        for run in data.get("runs", []):
            for kind, rows in (("an event", run.get("events", [])), ("a note", run.get("cue_notes", []))):
                for row in rows:
                    linked = (row.get("cue") or {}).get("number")
                    if linked is not None and linked not in numbers:
                        raise serializers.ValidationError(
                            {"runs": f"{run['label']} links {kind} to cue {format_number(linked)}, which isn't in the file."}
                        )
        return data


def repeats(values):
    seen = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None
