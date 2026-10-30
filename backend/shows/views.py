import json

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import backup, csv_io, report, services
from .access import ProductionRole, visible_productions
from .models import Cue, CueNote, Membership, Run
from .serializers import (
    CueEventSerializer,
    CueNoteSerializer,
    CueSerializer,
    CueTargetSerializer,
    HoldSerializer,
    InviteSerializer,
    MembershipSerializer,
    OptionalCueTargetSerializer,
    ProductionSerializer,
    RunDetailSerializer,
    RunSerializer,
    ReportEmailSerializer,
    RunStateSerializer,
)


ROLE_PERMISSIONS = [permissions.IsAuthenticated, ProductionRole]


class ProductionViewSet(viewsets.ModelViewSet):
    serializer_class = ProductionSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {
        "update": "edit",
        "partial_update": "edit",
        "destroy": "delete",
        "cues": "edit",
        "import_cues": "edit",
        "runs": "operate",
        "members": "share",
        # The copy belongs to whoever makes it, and holds nothing they can't
        # already read and export, so any role may duplicate.
        "duplicate": "view",
    }

    def get_queryset(self):
        # Tenant isolation: a production you're not on is a 404, not a 403.
        return visible_productions(self.request.user).select_related("owner__profile")

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        """A copy of the production and its cue list, without runs. Body fields override the copy's details."""
        production = self.get_object()
        details = ProductionSerializer(data=request.data, partial=True)
        details.is_valid(raise_exception=True)
        copy = backup.duplicate(production, request.user, **details.validated_data)
        return Response(ProductionSerializer(copy, context={"request": request}).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        production = self.get_object()
        response = JsonResponse(backup.export_production(production), json_dumps_params={"indent": 2})
        response["Content-Disposition"] = f'attachment; filename="{slugify(production.name)}.json"'
        return response

    @action(detail=False, methods=["post"], url_path="import")
    def import_production(self, request):
        """Upload (``file``) or post a production file as the body; always creates a new production."""
        upload = request.FILES.get("file")
        if upload:
            try:
                data = json.loads(upload.read())
            except (UnicodeDecodeError, json.JSONDecodeError):
                return Response({"detail": "The file is not valid JSON."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            data = request.data
        production = backup.import_production(request.user, backup.validate(data))
        return Response(ProductionSerializer(production, context={"request": request}).data, status=status.HTTP_201_CREATED)

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

    @action(detail=True, methods=["get", "post"])
    def members(self, request, pk=None):
        """Everyone on the production, owner first. POST adds a member by ``user`` (username or email) and ``role``."""
        production = self.get_object()
        if request.method == "GET":
            members = production.memberships.select_related("user__profile")
            return Response(
                {
                    "owner": ProductionSerializer(production, context={"request": request}).data["owner"],
                    "members": MembershipSerializer(members, many=True).data,
                }
            )

        invite = InviteSerializer(data=request.data, context={"production": production})
        invite.is_valid(raise_exception=True)
        membership = Membership.objects.create(production=production, **invite.validated_data)
        return Response(MembershipSerializer(membership).data, status=status.HTTP_201_CREATED)


class CueViewSet(
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CueSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "edit", "partial_update": "edit", "destroy": "edit"}

    def get_queryset(self):
        return Cue.objects.filter(production__in=visible_productions(self.request.user))


class RunViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
    """Runs are history, so there is no delete. Operator actions append events."""

    permission_classes = ROLE_PERMISSIONS
    # Unthrottled, except the actions that set their own scope (emailing a report).
    throttle_scope = None
    capabilities = {
        "update": "operate",
        "partial_update": "operate",
        "go": "operate",
        "back": "operate",
        "goto": "operate",
        "reset": "operate",
        "hold": "operate",
        "resume": "operate",
        "cue_notes": "operate",
        "end": "operate",
        "email_report": "operate",
    }

    def get_queryset(self):
        return Run.objects.filter(production__in=visible_productions(self.request.user)).prefetch_related(
            "events", "cue_notes__author__profile"
        )

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
        run = self.get_object()
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

    @action(detail=True, methods=["post"])
    def hold(self, request, pk=None):
        """Pause the run; ``reason`` is required. GO, BACK, GOTO and RESET are refused until a resume."""
        body = HoldSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        return self._act(request, pk, lambda run: services.hold(run, body.validated_data["reason"]))

    @action(detail=True, methods=["post"])
    def resume(self, request, pk=None):
        return self._act(request, pk, services.resume)

    @action(detail=True, methods=["get", "post"], url_path="notes")
    def cue_notes(self, request, pk=None):
        """Notes on cues in this run. POST ``cue`` (an id) and ``text``; works on an ended run too."""
        run = self.get_object()
        if request.method == "GET":
            return Response(CueNoteSerializer(run.cue_notes.select_related("author__profile"), many=True).data)
        serializer = CueNoteSerializer(data=request.data, context={"run": run})
        serializer.is_valid(raise_exception=True)
        serializer.save(run=run, author=request.user)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def export(self, request, pk=None):
        run = self.get_object()
        name = f"{slugify(run.production.name)}-{slugify(run.label)}-log.csv"
        return csv_response(csv_io.export_run(run), name)

    @action(detail=True, methods=["get"])
    def report(self, request, pk=None):
        """The show report: times, holds, scene lengths and notes (see report.py)."""
        return Response(report.build(self.get_object()))

    @action(detail=True, methods=["post"], url_path="report/email", throttle_scope="report_email")
    def email_report(self, request, pk=None):
        """Email the report, as text and HTML, to ``to`` (a list of addresses). One email each."""
        run = self.get_object()
        body = ReportEmailSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        to = body.validated_data["to"]

        built = report.build(run)
        subject, text, html = report.subject(built), report.as_text(built), report.as_html(built)
        reply_to = [request.user.email] if request.user.email else None
        messages = []
        for address in to:
            message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [address], reply_to=reply_to)
            message.attach_alternative(html, "text/html")
            messages.append(message)
        get_connection().send_messages(messages)
        return Response({"sent": len(messages), "to": to})

    @action(detail=True, methods=["post"])
    def end(self, request, pk=None):
        run = self.get_object()
        return Response(RunSerializer(services.end(run)).data)


class CueNoteViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Change a cue note's text, or delete it. Created through ``/runs/{id}/notes/``."""

    serializer_class = CueNoteSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "operate", "partial_update": "operate", "destroy": "operate"}

    def get_queryset(self):
        return CueNote.objects.filter(run__production__in=visible_productions(self.request.user)).select_related(
            "run__production", "author__profile"
        )


class MembershipViewSet(mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Change a member's role, or remove them. Anyone may remove themselves (leave)."""

    serializer_class = MembershipSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "share", "partial_update": "share", "destroy": "share"}

    def get_queryset(self):
        return Membership.objects.filter(production__in=visible_productions(self.request.user)).select_related(
            "production", "user__profile"
        )

    def check_object_permissions(self, request, membership):
        if self.action == "destroy" and membership.user_id == request.user.id:
            return
        super().check_object_permissions(request, membership)


def csv_response(body, filename):
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
