import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import profile_for
from shows.models import Cue, CueNote, Membership, Production


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def add_note(client, run, cue, text="Q late"):
    return client.post(f"/api/runs/{run.id}/notes/", {"cue": cue.id, "text": text}, format="json")


@pytest.mark.django_db
def test_a_note_records_the_cue_and_author(show):
    profile = profile_for(show.owner)
    profile.display_name = "Alice SM"
    profile.save()
    client = client_for(show.owner)

    response = add_note(client, show.run, show.cues["12"], "Late on the bell, tech 2")

    assert response.status_code == 201
    note = response.data
    assert (note["run"], note["cue"], note["cue_number"], note["cue_label"]) == (
        show.run.id,
        show.cues["12"].id,
        "12",
        "Cue 12",
    )
    assert (note["text"], note["author"]) == ("Late on the bell, tech 2", "Alice SM")
    assert client.get(f"/api/runs/{show.run.id}/notes/").data == [note]
    assert client.get(f"/api/runs/{show.run.id}/").data["cue_notes"] == [note]


@pytest.mark.django_db
def test_notes_are_apart_from_the_cue_and_the_log(show):
    add_note(client_for(show.owner), show.run, show.cues["1"])
    cue = Cue.objects.get(pk=show.cues["1"].pk)
    assert cue.notes == ""
    assert show.run.events.count() == 0


@pytest.mark.django_db
def test_editing_changes_only_the_text(show):
    client = client_for(show.owner)
    note = add_note(client, show.run, show.cues["1"], "Late").data

    edited = client.patch(f"/api/cue-notes/{note['id']}/", {"text": "Late, fixed in tech 3"}, format="json")
    assert edited.status_code == 200
    assert edited.data["text"] == "Late, fixed in tech 3"
    assert edited.data["updated_at"] > note["updated_at"]

    moved = client.patch(f"/api/cue-notes/{note['id']}/", {"cue": show.cues["2"].id}, format="json")
    assert moved.status_code == 400
    assert CueNote.objects.get(pk=note["id"]).cue == show.cues["1"]


@pytest.mark.django_db
def test_a_note_can_be_deleted(show):
    client = client_for(show.owner)
    note = add_note(client, show.run, show.cues["1"]).data
    assert client.delete(f"/api/cue-notes/{note['id']}/").status_code == 204
    assert CueNote.objects.count() == 0


@pytest.mark.django_db
def test_a_note_keeps_the_cue_it_was_about(show):
    client = client_for(show.owner)
    note = add_note(client, show.run, show.cues["12"]).data
    show.cues["12"].delete()
    kept = client.get(f"/api/runs/{show.run.id}/notes/").data[0]
    assert (kept["id"], kept["cue"], kept["cue_number"], kept["cue_label"]) == (note["id"], None, "12", "Cue 12")


@pytest.mark.django_db
def test_notes_can_be_written_after_the_run_ends(show):
    client = client_for(show.owner)
    client.post(f"/api/runs/{show.run.id}/end/")
    assert add_note(client, show.run, show.cues["1"]).status_code == 201


@pytest.mark.django_db
def test_a_note_needs_text_and_a_cue_from_this_production(show, make_user):
    client = client_for(show.owner)
    other = Production.objects.create(owner=show.owner, name="Other")
    stranger = Cue.objects.create(production=other, number=Decimal("1"))

    assert add_note(client, show.run, show.cues["1"], "").status_code == 400
    assert client.post(f"/api/runs/{show.run.id}/notes/", {"text": "No cue"}, format="json").status_code == 400
    wrong = add_note(client, show.run, stranger)
    assert wrong.status_code == 400
    assert wrong.data["cue"] == ["That cue is not in this production."]
    assert CueNote.objects.count() == 0


@pytest.mark.django_db
def test_viewers_read_notes_and_operators_write_them(show, make_user):
    viewer, operator = make_user("viewer"), make_user("operator")
    Membership.objects.create(production=show.production, user=viewer, role="viewer")
    Membership.objects.create(production=show.production, user=operator, role="operator")
    note = add_note(client_for(operator), show.run, show.cues["1"])
    assert note.status_code == 201
    as_viewer = client_for(viewer)

    assert as_viewer.get(f"/api/runs/{show.run.id}/notes/").status_code == 200
    assert add_note(as_viewer, show.run, show.cues["1"]).status_code == 403
    assert as_viewer.patch(f"/api/cue-notes/{note.data['id']}/", {"text": "x"}, format="json").status_code == 403
    assert as_viewer.delete(f"/api/cue-notes/{note.data['id']}/").status_code == 403
    assert client_for(operator).delete(f"/api/cue-notes/{note.data['id']}/").status_code == 204


@pytest.mark.django_db
def test_strangers_cannot_see_or_touch_notes(show, make_user):
    note = add_note(client_for(show.owner), show.run, show.cues["1"]).data
    stranger = client_for(make_user("mallory"))
    assert stranger.get(f"/api/runs/{show.run.id}/notes/").status_code == 404
    assert stranger.patch(f"/api/cue-notes/{note['id']}/", {"text": "x"}, format="json").status_code == 404
    assert stranger.delete(f"/api/cue-notes/{note['id']}/").status_code == 404


@pytest.mark.django_db
def test_notes_survive_a_backup_round_trip(show):
    client = client_for(show.owner)
    add_note(client, show.run, show.cues["12"], "Late")
    add_note(client, show.run, show.cues["2"], "Gone later")
    when = datetime(2026, 3, 14, 19, 30, tzinfo=timezone.utc)
    CueNote.objects.filter(cue_label="Cue 12").update(created_at=when, updated_at=when)
    show.cues["2"].delete()

    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])

    fields = ("cue__number", "cue_number", "cue_label", "text", "created_at", "updated_at")
    original = list(CueNote.objects.filter(run__production=show.production).values(*fields))
    restored = list(CueNote.objects.filter(run__production=copy).values(*fields))
    assert restored == original
    assert restored[0]["created_at"] == when
    assert [n["cue__number"] for n in restored] == [Decimal("12"), None]
