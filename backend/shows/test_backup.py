import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from shows.models import Cue, CueEvent, Production, Run

START = datetime(2026, 3, 14, 19, 30, tzinfo=timezone.utc)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def alice():
    return get_user_model().objects.create_user(username="alice", password="pw-for-tests")


@pytest.fixture
def bob():
    return get_user_model().objects.create_user(username="bob", password="pw-for-tests")


@pytest.fixture
def show(alice):
    """A production with cues 1, 2, 2.5 and one ended run.

    The run's log has a GO to cue 1, a GO to cue 2 (since renumbered to 3),
    a GO to a cue that has been deleted, and a reset. Every timestamp is set
    explicitly and distinct, so a lost or reordered time shows up.
    """
    production = Production.objects.create(
        owner=alice, name="Show A", company="Co", venue="Hall", opening_date="2026-03-14", closing_date="2026-03-28", notes="Notes"
    )
    one = Cue.objects.create(
        production=production, number=Decimal("1"), label="Open", page=3, scene="PRESHOW", time=Decimal("3.9"), follow="F2"
    )
    two = Cue.objects.create(production=production, number=Decimal("2"), label="Shift", down_time=Decimal("5"))
    gone = Cue.objects.create(production=production, number=Decimal("2.5"), label="Cut later")
    run = Run.objects.create(production=production, label="Preview 1", kind=Run.Kind.PREVIEW, notes="Late start")
    events = [
        CueEvent.objects.create(run=run, action="go", cue=one, cue_number=one.number, cue_label=one.label),
        CueEvent.objects.create(run=run, action="go", cue=two, cue_number=two.number, cue_label=two.label, note="late"),
        CueEvent.objects.create(run=run, action="go", cue=gone, cue_number=gone.number, cue_label=gone.label),
        CueEvent.objects.create(run=run, action="reset"),
    ]
    for i, event in enumerate(events):
        CueEvent.objects.filter(pk=event.pk).update(fired_at=START + timedelta(minutes=i))
    Run.objects.filter(pk=run.pk).update(
        created_at=START - timedelta(hours=1),
        scheduled_start=START - timedelta(minutes=5),
        started_at=START - timedelta(seconds=30),
        ended_at=START + timedelta(hours=2),
    )
    Cue.objects.filter(pk=two.pk).update(number=Decimal("3"))
    gone.delete()
    return production


def history(production):
    """Everything a backup should carry, without ids."""
    cues = list(production.cues.values("number", "label", "page", "notes", "scene", "time", "down_time", "duration", "follow"))
    runs = [
        {
            **Run.objects.filter(pk=run.pk).values("label", "kind", "created_at", "scheduled_start", "started_at", "ended_at", "notes").get(),
            "events": list(
                run.events.values("action", "cue__number", "cue_number", "cue_label", "fired_at", "note")
            ),
        }
        for run in production.runs.order_by("created_at")
    ]
    details = Production.objects.filter(pk=production.pk).values("name", "company", "venue", "opening_date", "closing_date", "notes").get()
    return {"details": details, "cues": cues, "runs": runs}


@pytest.mark.django_db
def test_export_then_import_recreates_the_production(show, alice):
    client = client_for(alice)
    exported = client.get(f"/api/productions/{show.id}/export/")
    assert exported.status_code == 200
    assert exported["Content-Disposition"] == 'attachment; filename="show-a.json"'
    data = json.loads(exported.content)
    assert data["format"] == "run-of-show/production"

    imported = client.post("/api/productions/import/", data, format="json")
    assert imported.status_code == 201
    copy = Production.objects.get(pk=imported.data["id"])
    assert copy.pk != show.pk and copy.owner == alice

    assert history(copy) == history(show)
    links = [e["cue__number"] for e in history(copy)["runs"][0]["events"]]
    assert links == [Decimal("1"), Decimal("3"), None, None]  # renumbered link kept, deleted cue stays unlinked
    assert {e.cue.production_id for e in CueEvent.objects.filter(run__production=copy, cue__isnull=False)} == {copy.pk}


@pytest.mark.django_db
def test_import_accepts_an_uploaded_file(show, alice):
    client = client_for(alice)
    body = client.get(f"/api/productions/{show.id}/export/").content
    upload = SimpleUploadedFile("show-a.json", body, content_type="application/json")
    response = client.post("/api/productions/import/", {"file": upload}, format="multipart")
    assert response.status_code == 201
    assert history(Production.objects.get(pk=response.data["id"])) == history(show)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "change, message",
    [
        (lambda d: d.update(format="something-else"), "not a Run of Show production file"),
        (lambda d: d.update(version=99), "newer version"),
        (lambda d: d["cues"].append(dict(d["cues"][0])), "Cue 1 appears more than once"),
        (lambda d: d["runs"].append(dict(d["runs"][0])), "appears more than once"),
        (lambda d: d["runs"][0]["events"][0].update(cue="42"), "cue 42, which isn't in the file"),
        (lambda d: d["cues"][0].update(follow="X9"), "Follow is a time in seconds"),
    ],
)
def test_import_rejects_a_bad_file_and_creates_nothing(show, alice, change, message):
    client = client_for(alice)
    data = json.loads(client.get(f"/api/productions/{show.id}/export/").content)
    change(data)
    before = (Production.objects.count(), Cue.objects.count(), Run.objects.count(), CueEvent.objects.count())

    response = client.post("/api/productions/import/", data, format="json")

    assert response.status_code == 400
    assert message in json.dumps(response.data)
    assert (Production.objects.count(), Cue.objects.count(), Run.objects.count(), CueEvent.objects.count()) == before


@pytest.mark.django_db
def test_a_file_from_elsewhere_gets_one_plain_message(alice):
    response = client_for(alice).post("/api/productions/import/", {"cues": "x"}, format="json")
    assert response.status_code == 400
    assert response.data == {"detail": "This is not a Run of Show production file."}


@pytest.mark.django_db
def test_import_rejects_a_file_that_is_not_json(alice):
    upload = SimpleUploadedFile("show.json", b"\xff not json", content_type="application/json")
    response = client_for(alice).post("/api/productions/import/", {"file": upload}, format="multipart")
    assert response.status_code == 400
    assert response.data["detail"] == "The file is not valid JSON."


@pytest.mark.django_db
def test_duplicate_copies_details_and_cues_but_not_runs(show, alice):
    before = history(show)
    response = client_for(alice).post(f"/api/productions/{show.id}/duplicate/", {}, format="json")
    assert response.status_code == 201
    copy = Production.objects.get(pk=response.data["id"])

    copied = history(copy)
    assert copied["details"] == {**before["details"], "name": "Show A (copy)"}
    assert copied["cues"] == before["cues"]
    assert copied["runs"] == []
    assert history(show) == before  # the original is untouched


@pytest.mark.django_db
def test_duplicate_takes_new_details(show, alice):
    response = client_for(alice).post(
        f"/api/productions/{show.id}/duplicate/", {"name": "Show A (tour)", "venue": "Other Hall"}, format="json"
    )
    assert response.status_code == 201
    assert (response.data["name"], response.data["venue"], response.data["company"]) == ("Show A (tour)", "Other Hall", "Co")


@pytest.mark.django_db
def test_another_users_production_cannot_be_exported_or_duplicated(show, bob):
    client = client_for(bob)
    assert client.get(f"/api/productions/{show.id}/export/").status_code == 404
    assert client.post(f"/api/productions/{show.id}/duplicate/", {}, format="json").status_code == 404
    assert Production.objects.count() == 1


@pytest.mark.django_db
def test_an_import_belongs_to_the_importer(show, alice, bob):
    data = json.loads(client_for(alice).get(f"/api/productions/{show.id}/export/").content)
    response = client_for(bob).post("/api/productions/import/", data, format="json")
    assert response.status_code == 201
    assert Production.objects.get(pk=response.data["id"]).owner == bob


@pytest.mark.django_db
def test_backup_endpoints_need_a_login(show):
    anon = APIClient()
    assert anon.get(f"/api/productions/{show.id}/export/").status_code == 401
    assert anon.post(f"/api/productions/{show.id}/duplicate/").status_code == 401
    assert anon.post("/api/productions/import/", {}, format="json").status_code == 401
