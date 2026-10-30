import importlib
from decimal import Decimal
from types import SimpleNamespace

import pytest
from rest_framework.test import APIClient

from shows.models import Cue, CueEvent, Production, Run


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def act(client, run, action, **body):
    return client.post(f"/api/runs/{run.id}/{action}/", body, format="json")


def active(client, run):
    return client.get(f"/api/runs/{run.id}/").data["state"]["active_number"]


@pytest.mark.django_db
def test_go_appends_event_without_touching_prior_events(show):
    client = client_for(show.owner)
    fields = ("id", "run_id", "action", "cue_id", "cue_number", "cue_label", "fired_at", "note")

    first = act(client, show.run, "go")
    assert first.status_code == 201
    before = list(CueEvent.objects.values(*fields))

    second = act(client, show.run, "go")
    assert second.status_code == 201
    assert second.data["event"]["id"] != first.data["event"]["id"]

    after = list(CueEvent.objects.values(*fields))
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before  # prior rows unchanged and still present


@pytest.mark.django_db
def test_unauthenticated_writes_are_rejected(show):
    anon = APIClient()
    cue = show.cues["1"]

    assert act(anon, show.run, "go").status_code == 401
    assert anon.post("/api/productions/", {"name": "Nope"}, format="json").status_code == 401
    assert anon.post(f"/api/productions/{show.production.id}/cues/", {"number": "9"}).status_code == 401
    assert anon.post(f"/api/productions/{show.production.id}/runs/", {"label": "X"}).status_code == 401
    assert anon.patch(f"/api/cues/{cue.id}/", {"label": "x"}, format="json").status_code == 401
    assert anon.delete(f"/api/cues/{cue.id}/").status_code == 401
    assert CueEvent.objects.count() == 0
    assert Cue.objects.get(pk=cue.pk).label == "Cue 1"


@pytest.mark.django_db
def test_user_cannot_see_or_change_another_users_production(show, make_user):
    mallory = client_for(make_user("mallory"))
    cue, run, prod = show.cues["1"], show.run, show.production

    assert mallory.get("/api/productions/").data == []
    assert mallory.get(f"/api/productions/{prod.id}/").status_code == 404
    assert mallory.get(f"/api/productions/{prod.id}/cues/").status_code == 404
    assert mallory.get(f"/api/productions/{prod.id}/runs/").status_code == 404
    assert mallory.get(f"/api/runs/{run.id}/").status_code == 404
    assert mallory.patch(f"/api/cues/{cue.id}/", {"label": "pwned"}, format="json").status_code == 404
    assert mallory.delete(f"/api/cues/{cue.id}/").status_code == 404
    for action in ("go", "back", "reset"):
        assert act(mallory, run, action).status_code == 404
    assert act(mallory, run, "goto", cue=cue.id).status_code == 404
    assert CueEvent.objects.count() == 0
    assert Cue.objects.filter(pk=cue.pk, label="Cue 1").exists()


@pytest.mark.django_db
def test_cue_cannot_be_fired_into_a_run_of_another_production(show, make_user):
    owner = show.owner
    other = Production.objects.create(owner=owner, name="Show B")
    stranger = Cue.objects.create(production=other, number=Decimal("7"))
    client = client_for(owner)

    assert act(client, show.run, "goto", cue=stranger.id).status_code == 400
    assert act(client, show.run, "go", cue=stranger.id).status_code == 400
    assert CueEvent.objects.count() == 0


@pytest.mark.django_db
def test_cues_sort_numerically_and_numbers_are_normalised(show):
    client = client_for(show.owner)
    numbers = [c["number"] for c in client.get(f"/api/productions/{show.production.id}/cues/").data]
    # Numeric order, not text order ("100" would sort before "12" as text).
    assert numbers == ["1", "2", "12", "12.5", "100"]


@pytest.mark.django_db
def test_cue_crud_and_duplicate_numbers(show):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/cues/"

    created = client.post(url, {"number": "12.25", "label": "Flicker", "notes": "n", "scene": "1.2"})
    assert created.status_code == 201
    assert created.data["number"] == "12.25"

    assert client.post(url, {"number": "12.5"}).status_code == 400  # already exists
    assert client.post(url, {"number": "0"}).status_code == 400
    assert client.post(url, {"number": "abc"}).status_code == 400

    cue_id = created.data["id"]
    assert client.patch(f"/api/cues/{cue_id}/", {"number": "12"}, format="json").status_code == 400
    patched = client.patch(f"/api/cues/{cue_id}/", {"number": "13", "label": "Flicker 2"}, format="json")
    assert patched.status_code == 200
    assert (patched.data["number"], patched.data["label"]) == ("13", "Flicker 2")
    # Re-sending its own number is not a clash with itself.
    assert client.patch(f"/api/cues/{cue_id}/", {"number": "13.0"}, format="json").status_code == 200

    assert client.delete(f"/api/cues/{cue_id}/").status_code == 204
    assert not Cue.objects.filter(pk=cue_id).exists()


@pytest.mark.django_db
def test_cue_times_and_follow(show):
    client = client_for(show.owner)
    cue = show.cues["12"]
    Cue.objects.filter(pk=cue.pk).update(time=Decimal("5"), duration=Decimal("13"))
    url = f"/api/cues/{cue.id}/"

    # Editing something else keeps Eos's duration; editing a time drops it.
    assert client.patch(url, {"label": "Lightning"}, format="json").data["duration"] == "13"
    assert client.patch(url, {"time": "5.00"}, format="json").data["duration"] == "13"  # same time
    timed = client.patch(url, {"time": "3.5", "down_time": "1"}, format="json").data
    assert (timed["time"], timed["down_time"], timed["duration"]) == ("3.5", "1", None)

    assert client.patch(url, {"follow": " f2 "}, format="json").data["follow"] == "F2"
    assert client.patch(url, {"follow": ""}, format="json").data["follow"] == ""
    assert client.patch(url, {"follow": "X2"}, format="json").status_code == 400
    # A bare number is a follow, and 0 is neither: most cues need nothing typed.
    assert client.patch(url, {"follow": "2.5"}, format="json").data["follow"] == "F2.5"
    assert client.patch(url, {"follow": "0"}, format="json").data["follow"] == ""
    assert client.patch(url, {"follow": "h0"}, format="json").data["follow"] == "H0"
    assert client.patch(url, {"follow": "2x"}, format="json").status_code == 400
    assert client.patch(url, {"time": "-1"}, format="json").status_code == 400


@pytest.mark.django_db
def test_operator_actions_move_the_active_cue(show):
    client = client_for(show.owner)
    run, cues = show.run, show.cues

    assert act(client, run, "back").status_code == 400  # nothing active yet
    assert act(client, run, "go").data["state"]["active_number"] == "1"
    assert act(client, run, "back").status_code == 400  # already at the first cue
    assert act(client, run, "go").data["state"]["active_number"] == "2"
    assert act(client, run, "go").data["state"]["next_cue"] == cues["12.5"].id

    # GO with a loaded cue fires that cue, skipping ahead.
    assert act(client, run, "go", cue=cues["100"].id).data["state"]["active_number"] == "100"
    assert act(client, run, "go").status_code == 400  # end of the list

    assert act(client, run, "back").data["state"]["active_number"] == "12.5"
    assert act(client, run, "goto", cue=cues["2"].id).data["state"]["active_number"] == "2"
    assert act(client, run, "goto").status_code == 400  # GOTO needs a cue
    assert act(client, run, "go").data["state"]["active_number"] == "12"

    state = act(client, run, "reset").data["state"]
    assert state["active_cue"] is None and state["next_cue"] == cues["1"].id
    assert act(client, run, "go").data["state"]["active_number"] == "1"

    actions = list(run.events.values_list("action", "cue_number"))
    assert actions == [
        ("go", Decimal("1")),
        ("go", Decimal("2")),
        ("go", Decimal("12")),
        ("go", Decimal("100")),
        ("back", Decimal("12.5")),
        ("goto", Decimal("2")),
        ("go", Decimal("12")),
        ("reset", None),
        ("go", Decimal("1")),
    ]


@pytest.mark.django_db
def test_log_snapshot_survives_editing_and_deleting_the_cue(show):
    client = client_for(show.owner)
    run, cue = show.run, show.cues["12"]

    act(client, run, "goto", cue=cue.id)
    client.patch(f"/api/cues/{cue.id}/", {"number": "15", "label": "Renamed"}, format="json")
    event = client.get(f"/api/runs/{run.id}/").data["events"][0]
    assert (event["cue_number"], event["cue_label"]) == ("12", "Cue 12")

    client.delete(f"/api/cues/{cue.id}/")
    detail = client.get(f"/api/runs/{run.id}/").data
    assert (detail["events"][0]["cue"], detail["events"][0]["cue_number"]) == (None, "12")
    # The active cue is gone, but GO still continues from its recorded number.
    assert detail["state"]["active_cue"] is None
    assert detail["state"]["next_cue"] == show.cues["12.5"].id
    assert act(client, run, "go").data["state"]["active_number"] == "12.5"


@pytest.mark.django_db
def test_runs_are_created_per_production_and_lock_when_ended(show):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/runs/"

    assert client.post(url, {"label": "Preview 1"}).status_code == 400  # label taken
    created = client.post(url, {"label": "Tech 1", "kind": "tech"})
    assert created.status_code == 201
    run = Run.objects.get(pk=created.data["id"])

    act(client, run, "go")
    assert client.post(f"/api/runs/{run.id}/end/").data["ended_at"] is not None
    assert act(client, run, "go").status_code == 409
    assert run.events.count() == 1


def test_migration_refuses_non_numeric_cue_numbers():
    migration = importlib.import_module("shows.migrations.0003_backfill_runs_and_numbers")
    ok = SimpleNamespace(id=1, production_id=1, number=" 12.5 ")
    assert migration.number_or_fail(ok) == Decimal("12.5")
    for bad in ("12a", "", "0", "-3", "NaN"):
        with pytest.raises(ValueError, match="not a positive decimal"):
            migration.number_or_fail(SimpleNamespace(id=1, production_id=1, number=bad))
