import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from shows.models import Cue, CueEvent, Production


@pytest.fixture
def make_user():
    def _make(username):
        return get_user_model().objects.create_user(username=username, password="pw-for-tests")

    return _make


@pytest.fixture
def production_with_cues(make_user):
    owner = make_user("alice")
    production = Production.objects.create(owner=owner, name="Show A")
    cues = [
        Cue.objects.create(production=production, number=str(n), label=f"Cue {n}", order=i)
        for i, n in enumerate([1, 2, 3])
    ]
    return owner, production, cues


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.mark.django_db
def test_fire_appends_event_without_touching_prior_events(production_with_cues):
    owner, production, cues = production_with_cues
    client = client_for(owner)

    first = client.post(f"/api/cues/{cues[0].id}/fire/", {"run_label": "Preview 1"}, format="json")
    assert first.status_code == 201
    before = list(CueEvent.objects.values("id", "cue_id", "run_label", "fired_at", "note"))

    second = client.post(f"/api/cues/{cues[1].id}/fire/", {"run_label": "Preview 1"}, format="json")
    assert second.status_code == 201
    assert second.data["id"] != first.data["id"]

    after = list(CueEvent.objects.values("id", "cue_id", "run_label", "fired_at", "note"))
    assert len(after) == len(before) + 1
    assert after[: len(before)] == before  # prior rows unchanged and still present

    log = client.get(f"/api/productions/{production.id}/events/").data
    assert [e["cue_number"] for e in log] == ["1", "2"]


@pytest.mark.django_db
def test_unauthenticated_writes_are_rejected(production_with_cues):
    _, production, cues = production_with_cues
    anon = APIClient()

    assert anon.post(f"/api/cues/{cues[0].id}/fire/", {}, format="json").status_code == 401
    assert anon.post("/api/productions/", {"name": "Nope"}, format="json").status_code == 401
    assert (
        anon.post(f"/api/productions/{production.id}/cues/", {"number": "9"}, format="json").status_code
        == 401
    )
    assert CueEvent.objects.count() == 0
    assert Production.objects.count() == 1


@pytest.mark.django_db
def test_user_cannot_see_or_fire_into_another_users_production(production_with_cues, make_user):
    _, production, cues = production_with_cues
    mallory = client_for(make_user("mallory"))

    assert mallory.get("/api/productions/").data == []
    assert mallory.get(f"/api/productions/{production.id}/").status_code == 404
    assert mallory.get(f"/api/productions/{production.id}/cues/").status_code == 404
    assert mallory.get(f"/api/productions/{production.id}/events/").status_code == 404
    assert mallory.post(f"/api/cues/{cues[0].id}/fire/", {}, format="json").status_code == 404
    assert CueEvent.objects.count() == 0
