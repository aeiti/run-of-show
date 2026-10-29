from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from .models import Cue, CueEvent, Production
from .serializers import (
    CueEventSerializer,
    CueSerializer,
    FireSerializer,
    ProductionSerializer,
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

        serializer = CueSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = serializer.validated_data.get("order")
        if order is None:
            last = production.cues.aggregate(m=Max("order"))["m"]
            order = 0 if last is None else last + 1
        serializer.save(production=production, order=order)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def events(self, request, pk=None):
        production = self.get_object()
        events = CueEvent.objects.filter(cue__production=production).select_related("cue")
        run = request.query_params.get("run")
        if run:
            events = events.filter(run_label=run)
        return Response(CueEventSerializer(events, many=True).data)


class CueViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = CueSerializer

    def get_queryset(self):
        return Cue.objects.filter(production__owner=self.request.user)

    @action(detail=True, methods=["post"])
    def fire(self, request, pk=None):
        cue = get_object_or_404(self.get_queryset(), pk=pk)
        params = FireSerializer(data=request.data)
        params.is_valid(raise_exception=True)
        event = CueEvent.objects.create(cue=cue, **params.validated_data)
        return Response(CueEventSerializer(event).data, status=status.HTTP_201_CREATED)
