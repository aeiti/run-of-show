from rest_framework import serializers

from .models import Cue, CueEvent, Production


class ProductionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Production
        fields = ["id", "name", "venue", "performance_date", "created_at"]
        read_only_fields = ["id", "created_at"]


class CueSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(required=False, min_value=0)

    class Meta:
        model = Cue
        fields = ["id", "number", "label", "page", "order"]
        read_only_fields = ["id"]


class CueEventSerializer(serializers.ModelSerializer):
    cue_number = serializers.CharField(source="cue.number", read_only=True)
    cue_label = serializers.CharField(source="cue.label", read_only=True)

    class Meta:
        model = CueEvent
        fields = ["id", "cue", "cue_number", "cue_label", "run_label", "fired_at", "note"]
        read_only_fields = ["id", "cue", "fired_at"]


class FireSerializer(serializers.Serializer):
    run_label = serializers.CharField(max_length=100, required=False, default="Run")
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")
