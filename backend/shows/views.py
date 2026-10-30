from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.text import slugify
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import csv_io, services
from .models import Cue, Production, Run
from .serializers import (
    CueEventSerializer,
    CueSerializer,
    CueTargetSerializer,
    OptionalCueTargetSerializer,
    ProductionSerializer,
    RunDetailSerializer,
    RunSerializer,
    RunStateSerializer,
)


class ProductionViewSet(viewsets.ModelViewSet):
    serializer_class = ProductionSerializer

    def get_queryset(self):
        # Tenant isolation: another user's production is a 404, not a 403.
        return Production.objects.filter(owner=self.request.user)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["get", "post"])
    def cues(self, request, pk=None):
        production = self.get_object()
        if request.method == "GET":
            return Response(CueSerializer(production.cues.all(), many=True).data)

        serializer = CueSerializer(data=request.data, context={"production": production})
        serializer.is_valid(raise_exception=True)
        serializer.save(production=production)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"], url_path="cues/import")
    def import_cues(self, request, pk=None):
        """Upload (``file``) or paste (``text``) a cue list. ``dry_run`` defaults to true."""
        production = self.get_object()
        upload = request.FILES.get("file")
        text = upload.read() if upload else request.data.get("text", "")
        dry_run = str(request.data.get("dry_run", "true")).lower() != "false"
        try:
            # Always planned against the current cue list, never a plan sent by the client.
            planned = csv_io.plan(
                production,
                text,
                mode=request.data.get("mode", "merge"),
                eos_list=request.data.get("list") or None,
            )
        except csv_io.CsvImportError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        if not dry_run:
            if planned["summary"] is None:
                return Response({"detail": "Choose which Eos cue list to import."}, status=status.HTTP_400_BAD_REQUEST)
            csv_io.apply(production, planned)
        return Response({**csv_io.public(planned), "applied": not dry_run})

    @action(detail=True, methods=["get"], url_path="cues/export")
    def export_cues(self, request, pk=None):
        production = self.get_object()
        return csv_response(csv_io.export_cues(production), f"{slugify(production.name)}-cues.csv")

    @action(detail=True, methods=["get", "post"])
    def runs(self, request, pk=None):
        production = self.get_object()
        if request.method == "GET":
            return Response(RunSerializer(production.runs.all(), many=True).data)

        serializer = RunSerializer(data=request.data, context={"production": production})
        serializer.is_valid(raise_exception=True)
        serializer.save(production=production)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class CueViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CueSerializer

    def get_queryset(self):
        return Cue.objects.filter(production__owner=self.request.user)


class RunViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Runs are history, so there is no delete. Operator actions append events."""

    def get_queryset(self):
        return Run.objects.filter(production__owner=self.request.user).prefetch_related("events")

    def get_serializer_class(self):
        return RunDetailSerializer if self.action == "retrieve" else RunSerializer

    def _respond(self, run, event):
        return Response(
            {
                "event": CueEventSerializer(event).data,
                "state": RunStateSerializer(services.run_state(run)).data,
            },
            status=status.HTTP_201_CREATED,
        )

    def _act(self, request, pk, fn, target_serializer=None):
        run = get_object_or_404(self.get_queryset(), pk=pk)
        kwargs = {}
        if target_serializer is not None:
            target = target_serializer(data=request.data)
            target.is_valid(raise_exception=True)
            if target.validated_data.get("cue") is not None:
                kwargs["cue_id"] = target.validated_data["cue"]
        try:
            event = fn(run, **kwargs)
        except services.RunActionError as e:
            return Response({"detail": str(e)}, status=e.status)
        return self._respond(run, event)

    @action(detail=True, methods=["post"])
    def go(self, request, pk=None):
        return self._act(request, pk, services.go, OptionalCueTargetSerializer)

    @action(detail=True, methods=["post"])
    def back(self, request, pk=None):
        return self._act(request, pk, services.back)

    @action(detail=True, methods=["post"])
    def goto(self, request, pk=None):
        return self._act(request, pk, services.goto, CueTargetSerializer)

    @action(detail=True, methods=["post"])
    def reset(self, request, pk=None):
        return self._act(request, pk, services.reset)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        run = get_object_or_404(self.get_queryset(), pk=pk)
        name = f"{slugify(run.production.name)}-{slugify(run.label)}-log.csv"
        return csv_response(csv_io.export_run(run), name)

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        run = get_object_or_404(self.get_queryset(), pk=pk)
        return Response(RunSerializer(services.end(run)).data)


def csv_response(body, filename):
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
