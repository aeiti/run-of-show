import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from django.utils import timezone as django_timezone
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
def test_a_note_needs_text_and_any_cue_from_this_production(show, make_user):
    client = client_for(show.owner)
    other = Production.objects.create(owner=show.owner, name="Other")
    stranger = Cue.objects.create(production=other, number=Decimal("1"))

    assert add_note(client, show.run, show.cues["1"], "").status_code == 400
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


@pytest.mark.django_db
def test_a_note_needs_no_cue(show):
    client = client_for(show.owner)
    for body in ({"text": "Before the first GO"}, {"text": "At the act break", "cue": None}):
        response = client.post(f"/api/runs/{show.run.id}/notes/", body, format="json")
        assert response.status_code == 201
        assert (response.data["cue"], response.data["cue_number"], response.data["cue_label"]) == (None, None, "")


@pytest.mark.django_db
def test_a_live_note_is_stamped_when_it_is_written(show):
    client = client_for(show.owner)
    before = django_timezone.now()
    note = add_note(client, show.run, show.cues["1"]).data
    stamped = CueNote.objects.get(pk=note["id"]).at
    assert before <= stamped <= django_timezone.now()
    assert note["added_later"] is False

    # Its time can't be set, then or afterwards.
    chosen = {"text": "Late", "at": "2026-03-14T19:40:00Z"}
    assert client.post(f"/api/runs/{show.run.id}/notes/", chosen, format="json").status_code == 400
    moved = client.patch(f"/api/cue-notes/{note['id']}/", {"at": "2026-03-14T19:40:00Z"}, format="json")
    assert moved.status_code == 400
    assert CueNote.objects.get(pk=note["id"]).at == stamped


@pytest.mark.django_db
def test_a_note_added_later_takes_a_time_or_none(show):
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/notes/"
    timed = client.post(
        url, {"text": "Missed the bell", "cue": show.cues["12"].id, "at": "2026-03-14T19:40:00Z", "added_later": True},
        format="json",
    ).data
    untimed = client.post(url, {"text": "Thank you, crew", "added_later": True}, format="json").data
    assert timed["at"] == "2026-03-14T19:40:00Z" and timed["cue_number"] == "12"
    assert untimed["at"] is None

    # Its time can be changed, but it stays a note added later.
    moved = client.patch(f"/api/cue-notes/{timed['id']}/", {"at": "2026-03-14T19:41:00Z"}, format="json")
    assert moved.status_code == 200 and moved.data["at"] == "2026-03-14T19:41:00Z"
    flipped = client.patch(f"/api/cue-notes/{timed['id']}/", {"added_later": False}, format="json")
    assert flipped.status_code == 400
    assert CueNote.objects.get(pk=timed["id"]).added_later is True


@pytest.mark.django_db
def test_a_follow_up_records_who_wrote_it_and_keeps_the_live_text(show, make_user):
    operator = make_user("olive")
    Membership.objects.create(production=show.production, user=operator, role="operator")
    note = add_note(client_for(show.owner), show.run, show.cues["1"], "Q1 late").data
    assert (note["follow_up"], note["follow_up_by"], note["follow_up_at"]) == ("", "", None)

    written = client_for(operator).patch(
        f"/api/cue-notes/{note['id']}/", {"follow_up": "Board op missed the standby; fixed for tomorrow."}, format="json"
    )
    assert written.status_code == 200
    assert (written.data["text"], written.data["author"]) == ("Q1 late", "alice")
    assert (written.data["follow_up"], written.data["follow_up_by"]) == (
        "Board op missed the standby; fixed for tomorrow.",
        "olive",
    )
    assert written.data["follow_up_at"] is not None

    # Editing only the text leaves the follow-up's author alone; clearing the follow-up clears them.
    retyped = client_for(show.owner).patch(f"/api/cue-notes/{note['id']}/", {"text": "Q1 late (GO)"}, format="json")
    assert retyped.data["follow_up_by"] == "olive"
    cleared = client_for(show.owner).patch(f"/api/cue-notes/{note['id']}/", {"follow_up": ""}, format="json")
    assert (cleared.data["follow_up"], cleared.data["follow_up_by"], cleared.data["follow_up_at"]) == ("", "", None)


@pytest.mark.django_db
def test_performance_notes_survive_a_backup_round_trip(show):
    client = client_for(show.owner)
    client.post(f"/api/runs/{show.run.id}/notes/", {"text": "No cue"}, format="json")
    client.post(f"/api/runs/{show.run.id}/notes/", {"text": "Later", "added_later": True}, format="json")
    first = CueNote.objects.get(text="No cue")
    client.patch(f"/api/cue-notes/{first.id}/", {"follow_up": "Explained"}, format="json")

    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])

    fields = ("text", "at", "added_later", "follow_up", "follow_up_at", "created_at")
    original = list(CueNote.objects.filter(run__production=show.production).values(*fields))
    assert list(CueNote.objects.filter(run__production=copy).values(*fields)) == original


@pytest.mark.django_db
def test_notes_from_an_older_backup_are_stamped_when_they_were_written(show):
    client = client_for(show.owner)
    add_note(client, show.run, show.cues["1"], "Old note")
    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    for run in data["runs"]:
        for note in run["cue_notes"]:
            for field in ("at", "added_later", "follow_up", "follow_up_at"):
                del note[field]
    when = "2026-03-14T19:45:00Z"
    data["runs"][0]["cue_notes"][0]["created_at"] = when

    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])
    restored = CueNote.objects.get(run__production=copy)
    assert restored.at == restored.created_at == datetime(2026, 3, 14, 19, 45, tzinfo=timezone.utc)
    assert restored.added_later is False


@pytest.mark.django_db
def test_a_note_goes_in_one_of_the_productions_sections(show):
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/notes/"
    note = client.post(url, {"text": "Q12 bumped", "cue": show.cues["12"].id, "section": "Lighting"}, format="json")
    assert note.status_code == 201 and note.data["section"] == "Lighting"
    assert note.data["show_cue"] is False
    assert client.post(url, {"text": "Unsorted"}, format="json").data["section"] == ""

    wrong = client.post(url, {"text": "x", "section": "Catering"}, format="json")
    assert wrong.status_code == 400
    assert wrong.data["section"] == ["'Catering' isn't one of this production's note sections."]

    moved = client.patch(f"/api/cue-notes/{note.data['id']}/", {"section": "Sound", "show_cue": True}, format="json")
    assert (moved.data["section"], moved.data["show_cue"]) == ("Sound", True)


@pytest.mark.django_db
def test_a_production_sets_its_own_note_sections(show, make_user):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/"
    assert client.get(url).data["note_sections"][:2] == ["Absences/Lateness", "Injury/Illness"]

    saved = client.patch(url, {"note_sections": [" Performance ", "", "Technical"]}, format="json")
    assert saved.status_code == 200 and saved.data["note_sections"] == ["Performance", "Technical"]
    twice = client.patch(url, {"note_sections": ["Tech", "tech"]}, format="json")
    assert twice.status_code == 400

    # An operator can't change them; only those who edit the production.
    operator = make_user("olive")
    Membership.objects.create(production=show.production, user=operator, role="operator")
    assert client_for(operator).patch(url, {"note_sections": ["Mine"]}, format="json").status_code == 403


@pytest.mark.django_db
def test_sections_and_old_run_notes_come_through_a_backup(show):
    client = client_for(show.owner)
    client.patch(f"/api/productions/{show.production.id}/", {"note_sections": ["Show", "Tech"]}, format="json")
    client.post(f"/api/runs/{show.run.id}/notes/", {"text": "Q1 late", "section": "Tech"}, format="json")
    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    # A file from before 0016 carries the run's free-text notes.
    data["runs"][0]["notes"] = "Patron fell in row F."

    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])
    assert copy.sections == ["Show", "Tech"]
    notes = list(CueNote.objects.filter(run__production=copy).values_list("text", "section", "added_later"))
    assert notes == [("Q1 late", "Tech", False), ("Patron fell in row F.", "Show", True)]
