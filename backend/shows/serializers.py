from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework import serializers

from .models import FOLLOW_VALIDATOR, Cue, CueEvent, Production, Run, format_number
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


class ProductionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Production
        fields = ["id", "name", "company", "venue", "performance_date", "notes", "created_at"]
        read_only_fields = ["id", "created_at"]


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


class RunStateSerializer(serializers.Serializer):
    active_cue = serializers.IntegerField(allow_null=True)
    active_number = CueNumberField(allow_null=True)
    next_cue = serializers.IntegerField(allow_null=True)


class RunDetailSerializer(RunSerializer):
    events = CueEventSerializer(many=True, read_only=True)
    state = serializers.SerializerMethodField()

    class Meta(RunSerializer.Meta):
        fields = RunSerializer.Meta.fields + ["events", "state"]

    def get_state(self, run):
        return RunStateSerializer(run_state(run)).data


class CueTargetSerializer(serializers.Serializer):
    cue = serializers.IntegerField()


class OptionalCueTargetSerializer(serializers.Serializer):
    cue = serializers.IntegerField(required=False, allow_null=True)


# Whole-production backup (see backup.py). The same serializers write the
# file and read it back, so an export always imports.

BACKUP_FORMAT = "run-of-show/production"
BACKUP_VERSION = 1


class BackupProductionSerializer(ProductionSerializer):
    class Meta(ProductionSerializer.Meta):
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


class BackupRunSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField()
    events = BackupEventSerializer(many=True, required=False)

    class Meta:
        model = Run
        fields = ["label", "kind", "created_at", "ended_at", "notes", "events"]


class BackupSerializer(serializers.Serializer):
    format = serializers.CharField()
    version = serializers.IntegerField()
    exported_at = serializers.DateTimeField(required=False)
    production = BackupProductionSerializer()
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
            for event in run.get("events", []):
                linked = (event.get("cue") or {}).get("number")
                if linked is not None and linked not in numbers:
                    raise serializers.ValidationError(
                        {"runs": f"{run['label']} links an event to cue {format_number(linked)}, which isn't in the file."}
                    )
        return data


def repeats(values):
    seen = set()
    for value in values:
        if value in seen:
            return value
        seen.add(value)
    return None
