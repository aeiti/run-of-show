import pytest
from rest_framework.test import APIClient

from shows import csv_io
from shows.models import CueEvent, Membership


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def act(client, run, action, **body):
    return client.post(f"/api/runs/{run.id}/{action}/", body, format="json")


@pytest.mark.django_db
def test_hold_pauses_the_run_with_a_reason_until_resume(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    act(client, show.run, "go")

    held = act(client, show.run, "hold", reason="Audience medical")
    assert held.status_code == 201
    assert held.data["event"]["action"] == "hold"
    assert held.data["event"]["note"] == "Audience medical"
    # The hold records the active cue but doesn't move it.
    assert (held.data["event"]["cue_number"], held.data["event"]["cue_label"]) == ("2", "Cue 2")
    state = held.data["state"]
    assert state["active_number"] == "2" and state["next_cue"] == show.cues["12"].id
    assert state["hold"]["reason"] == "Audience medical"
    assert state["hold"]["since"] == held.data["event"]["fired_at"]
    assert client.get(f"/api/runs/{show.run.id}/").data["state"]["hold"]["reason"] == "Audience medical"

    resumed = act(client, show.run, "resume")
    assert resumed.status_code == 201
    assert resumed.data["event"]["cue_number"] == "2"
    assert resumed.data["state"]["hold"] is None
    # GO carries on from the cue that was active before the hold.
    assert act(client, show.run, "go").data["state"]["active_number"] == "12"


@pytest.mark.django_db
@pytest.mark.parametrize("action, body", [("go", {}), ("back", {}), ("goto", {"cue": "cue-1"}), ("reset", {})])
def test_no_cue_action_while_held(show, action, body):
    client = client_for(show.owner)
    act(client, show.run, "go")
    act(client, show.run, "go")
    act(client, show.run, "hold", reason="Fly bar stuck")
    if "cue" in body:
        body = {"cue": show.cues["1"].id}

    response = act(client, show.run, action, **body)

    assert response.status_code == 409
    assert response.data["detail"] == "The run is on hold. Resume it first."
    assert list(CueEvent.objects.values_list("action", flat=True)) == ["go", "go", "hold"]


@pytest.mark.django_db
def test_hold_needs_a_reason_and_cannot_stack(show):
    client = client_for(show.owner)
    assert act(client, show.run, "hold").status_code == 400
    assert act(client, show.run, "hold", reason="").status_code == 400
    assert act(client, show.run, "hold", reason="x" * 501).status_code == 400
    assert act(client, show.run, "resume").status_code == 409  # not on hold

    assert act(client, show.run, "hold", reason="Late house").status_code == 201
    again = act(client, show.run, "hold", reason="Still late")
    assert again.status_code == 409
    assert again.data["detail"] == "The run is already on hold."
    assert CueEvent.objects.count() == 1


@pytest.mark.django_db
def test_hold_before_any_cue_records_no_cue(show):
    client = client_for(show.owner)
    held = act(client, show.run, "hold", reason="Late house")
    assert held.data["event"]["cue_number"] is None
    assert held.data["state"]["active_cue"] is None
    act(client, show.run, "resume")
    assert act(client, show.run, "go").data["state"]["active_number"] == "1"


@pytest.mark.django_db
def test_hold_after_a_reset_keeps_the_reset(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    act(client, show.run, "reset")
    act(client, show.run, "hold", reason="Reset the deck")
    resumed = act(client, show.run, "resume")
    assert resumed.data["state"]["active_number"] is None
    assert act(client, show.run, "go").data["state"]["active_number"] == "1"


@pytest.mark.django_db
def test_a_held_run_can_end_and_then_nothing_more(show):
    client = client_for(show.owner)
    act(client, show.run, "hold", reason="Show stopped")
    assert act(client, show.run, "end").status_code == 200
    assert act(client, show.run, "resume").status_code == 409
    assert act(client, show.run, "hold", reason="x").status_code == 409


@pytest.mark.django_db
def test_viewers_cannot_hold_and_operators_can(show, make_user):
    viewer, operator = make_user("viewer"), make_user("operator")
    Membership.objects.create(production=show.production, user=viewer, role="viewer")
    Membership.objects.create(production=show.production, user=operator, role="operator")

    assert act(client_for(viewer), show.run, "hold", reason="x").status_code == 403
    assert act(client_for(operator), show.run, "hold", reason="x").status_code == 201
    assert act(client_for(viewer), show.run, "resume").status_code == 403
    assert act(client_for(operator), show.run, "resume").status_code == 201


@pytest.mark.django_db
def test_holds_are_in_the_csv_log(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    act(client, show.run, "hold", reason="Audience medical")
    act(client, show.run, "resume")
    rows = [line.split(",") for line in csv_io.export_run(show.run).splitlines()[1:]]
    assert [(r[2], r[3], r[5]) for r in rows] == [("go", "1", ""), ("hold", "1", "Audience medical"), ("resume", "1", "")]
