import json
import os

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, get_connection
from django.db import transaction
from django.db.models import Max
from django.http import FileResponse, HttpResponse, JsonResponse
from django.utils.text import slugify
from rest_framework import mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from . import backup, csv_io, live, report, services, uploads
from .access import ProductionRole, visible_productions
from .console import supervisor
from .models import Cue, CueNote, EosConsole, Membership, Production, ProductionFile, Run
from .serializers import (
    CueEventSerializer,
    CueNoteSerializer,
    CueSerializer,
    CueTargetSerializer,
    EosConsoleSerializer,
    FileUploadSerializer,
    HoldSerializer,
    InviteSerializer,
    LogoUploadSerializer,
    MembershipSerializer,
    OptionalCueTargetSerializer,
    ProductionFileSerializer,
    ProductionSerializer,
    RunDetailSerializer,
    RunSerializer,
    ReportEmailSerializer,
    RunStateSerializer,
)


ROLE_PERMISSIONS = [permissions.IsAuthenticated, ProductionRole]


class LiveUpdates:
    """Tells open boards about each successful write (see ``live.py``).

    ``live_topics`` maps an action to the message type it sends. The
    production is the one behind the object the action looked up.
    """

    live_topics = {}
    live_production_id = None

    def get_object(self):
        obj = super().get_object()
        if isinstance(obj, Production):
            self.live_production_id = obj.pk
        else:
            self.live_production_id = obj.run.production_id if isinstance(obj, CueNote) else obj.production_id
        return obj

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        topic = self.live_topics.get(getattr(self, "action", None))
        changed = request.method not in permissions.SAFE_METHODS and 200 <= response.status_code < 300
        if topic and changed and self.live_production_id is not None:
            message = self.live_message(topic, response)
            if message is not None:
                live.broadcast(self.live_production_id, message)
        return response

    def live_message(self, topic, response):
        return {"type": topic}


class ProductionViewSet(LiveUpdates, viewsets.ModelViewSet):
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
        "files": "edit",
        "logo": "edit",
        "console": "edit",
        # The copy belongs to whoever makes it, and holds nothing they can't
        # already read and export, so any role may duplicate.
        "duplicate": "view",
    }
    live_topics = {
        "update": "production",
        "partial_update": "production",
        "destroy": "production.deleted",
        "cues": "cues",
        "import_cues": "cues",
        "runs": "runs",
        "members": "access",
        "files": "files",
        "logo": "production",
    }

    def live_message(self, topic, response):
        # A dry-run import changes nothing.
        if self.action == "import_cues" and not response.data.get("applied"):
            return None
        return super().live_message(topic, response)

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
    def files(self, request, pk=None):
        """Every version of every file, newest version first. POST ``file`` and ``kind``; a kind and name already there adds a version."""
        production = self.get_object()
        if request.method == "GET":
            return Response(ProductionFileSerializer(production.files.select_related("uploaded_by__profile"), many=True).data)

        upload = FileUploadSerializer(data=request.data)
        upload.is_valid(raise_exception=True)
        kind, name, file = (upload.validated_data[k] for k in ("kind", "name", "file"))
        with transaction.atomic():
            # Lock the production so two uploads of one name can't take the same version.
            Production.objects.select_for_update().filter(pk=production.pk).first()
            latest = production.files.filter(kind=kind, name=name).aggregate(v=Max("version"))["v"] or 0
            created = ProductionFile.objects.create(
                production=production,
                kind=kind,
                name=name,
                version=latest + 1,
                file=file,
                size=file.size,
                content_type="application/pdf" if kind == ProductionFile.Kind.SCRIPT else uploads.content_type_for(name),
                uploaded_by=request.user,
            )
        return Response(ProductionFileSerializer(created).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "put", "delete"])
    def logo(self, request, pk=None):
        """GET the image; PUT a new one as ``file`` (replacing any), or DELETE it. Changes return the production."""
        production = self.get_object()
        if request.method == "GET":
            if not production.logo:
                return Response({"detail": "This production has no logo."}, status=status.HTTP_404_NOT_FOUND)
            name = f"{slugify(production.name) or 'production'}-logo{os.path.splitext(production.logo.name)[1]}"
            return stored_file_response(production.logo, name, uploads.content_type_for(production.logo.name))

        if request.method == "PUT":
            upload = LogoUploadSerializer(data=request.data)
            upload.is_valid(raise_exception=True)
        with transaction.atomic():
            # The old image is deleted once the change commits.
            uploads.delete_stored(production.logo)
            if request.method == "PUT":
                production.logo.save(f"logo.{upload.validated_data['ext']}", upload.validated_data["file"], save=False)
            else:
                production.logo = ""
            production.save(update_fields=["logo"])
        return Response(ProductionSerializer(production, context={"request": request}).data)

    @action(detail=True, methods=["get", "put"])
    def console(self, request, pk=None):
        """The Eos console settings and the listener's status. PUT changes the settings, which restarts the listener."""
        production = self.get_object()
        config = EosConsole.objects.filter(production=production).first()
        if request.method == "PUT":
            serializer = EosConsoleSerializer(config, data=request.data, context={"production": production})
            serializer.is_valid(raise_exception=True)
            config = serializer.save(production=production)
        data = EosConsoleSerializer(config or EosConsole(production=production)).data
        return Response({**data, "status": supervisor.status(production.id), "recent": supervisor.recent(production.id)})

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
    LiveUpdates,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    serializer_class = CueSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "edit", "partial_update": "edit", "destroy": "edit"}
    live_topics = {"update": "cues", "partial_update": "cues", "destroy": "cues"}

    def get_queryset(self):
        return Cue.objects.filter(production__in=visible_productions(self.request.user))


class RunViewSet(LiveUpdates, mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet):
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
    live_topics = {
        "update": "runs",
        "partial_update": "runs",
        "end": "runs",
        "cue_notes": "notes",
        **{name: "run.event" for name in ("go", "back", "goto", "reset", "hold", "resume")},
    }

    def live_message(self, topic, response):
        run = int(self.kwargs["pk"])
        if topic == "run.event":
            # Everything a board needs to play the action without refetching.
            return {"type": topic, "run": run, "event": response.data["event"], "state": response.data["state"]}
        return {"type": topic, "run": run}

    def get_queryset(self):
        return Run.objects.filter(production__in=visible_productions(self.request.user)).prefetch_related(
            "events", "cue_notes__author__profile", "cue_notes__follow_up_by__profile", "console_events"
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
        response = self._act(request, pk, lambda run: services.resume(run, author=request.user))
        if response.status_code == status.HTTP_201_CREATED:
            # The resume added a note about the hold.
            live.broadcast(self.live_production_id, {"type": "notes", "run": int(pk)})
        return response

    @action(detail=True, methods=["get", "post"], url_path="notes")
    def cue_notes(self, request, pk=None):
        """Performance notes in this run. POST ``text``, and ``cue`` (an id) if it was at one; works on an ended run too."""
        run = self.get_object()
        if request.method == "GET":
            return Response(CueNoteSerializer(run.cue_notes.select_related("author__profile", "follow_up_by__profile"), many=True).data)
        serializer = CueNoteSerializer(data=request.data, context={"run": run, "request": request})
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
        stamps = body.validated_data["stamps"]
        subject, text, html = report.subject(built), report.as_text(built, stamps), report.as_html(built, stamps)
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


class CueNoteViewSet(LiveUpdates, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Change a performance note's text or follow-up, or delete it. Created through ``/runs/{id}/notes/``."""

    serializer_class = CueNoteSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "operate", "partial_update": "operate", "destroy": "operate"}
    live_topics = {"update": "notes", "partial_update": "notes", "destroy": "notes"}

    def live_message(self, topic, response):
        return {"type": topic, "run": self.note_run_id}

    def get_object(self):
        note = super().get_object()
        self.note_run_id = note.run_id
        return note

    def get_queryset(self):
        return CueNote.objects.filter(run__production__in=visible_productions(self.request.user)).select_related(
            "run__production", "author__profile", "follow_up_by__profile"
        )


class ProductionFileViewSet(LiveUpdates, mixins.RetrieveModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """One version of a file: its details, its contents (``download/``), or delete it. Uploaded through ``/productions/{id}/files/``."""

    serializer_class = ProductionFileSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"destroy": "edit"}
    live_topics = {"destroy": "files"}

    def get_queryset(self):
        return ProductionFile.objects.filter(production__in=visible_productions(self.request.user)).select_related(
            "production", "uploaded_by__profile"
        )

    @action(detail=True, methods=["get"])
    def download(self, request, pk=None):
        f = self.get_object()
        return stored_file_response(f.file, f.name, f.content_type)


class MembershipViewSet(LiveUpdates, mixins.UpdateModelMixin, mixins.DestroyModelMixin, viewsets.GenericViewSet):
    """Change a member's role, or remove them. Anyone may remove themselves (leave)."""

    serializer_class = MembershipSerializer
    permission_classes = ROLE_PERMISSIONS
    capabilities = {"update": "share", "partial_update": "share", "destroy": "share"}
    live_topics = {"update": "access", "partial_update": "access", "destroy": "access"}

    def get_queryset(self):
        return Membership.objects.filter(production__in=visible_productions(self.request.user)).select_related(
            "production", "user__profile"
        )

    def check_object_permissions(self, request, membership):
        if self.action == "destroy" and membership.user_id == request.user.id:
            return
        super().check_object_permissions(request, membership)


def stored_file_response(field_file, filename, content_type):
    # Always an attachment: these come from users, and must never render as a
    # page on the API's origin. The app fetches them and makes a blob instead.
    return FileResponse(field_file.open("rb"), as_attachment=True, filename=filename, content_type=content_type)


def csv_response(body, filename):
    response = HttpResponse(body, content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
