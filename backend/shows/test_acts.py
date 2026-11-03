"""Acts: marked from the board or by flagged cues, corrected by hand, and the report's times block."""

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from shows import report, services
from shows.models import Act, CueEvent, Membership, Production, Run


def at(hour, minute, second=0):
    return datetime(2026, 3, 14, hour, minute, second, tzinfo=timezone.utc)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def act(client, run, action, **body):
    return client.post(f"/api/runs/{run.id}/{action}/", body, format="json")


def flag(show, number, mark):
    cue = show.cues[number]
    cue.act_mark = mark
    cue.save()


# Marking acts


@pytest.mark.django_db
def test_the_board_brings_acts_up_and_down_in_turn(show):
    client = client_for(show.owner)
    up = act(client, show.run, "act-up")
    assert up.status_code == 200
    assert up.data["state"]["act"]["number"] == 1 and up.data["state"]["acts"] == 1

    assert act(client, show.run, "act-up").status_code == 409
    down = act(client, show.run, "act-down")
    assert down.data["state"]["act"] is None and down.data["state"]["acts"] == 1
    assert act(client, show.run, "act-down").data["detail"] == "No act is up."

    assert act(client, show.run, "act-up").data["state"]["act"]["number"] == 2
    acts = list(show.run.acts.values_list("number", "down_at"))
    assert [n for n, _ in acts] == [1, 2] and acts[0][1] is not None and acts[1][1] is None
    # The run's detail carries its acts.
    assert [a["number"] for a in client.get(f"/api/runs/{show.run.id}/").data["acts"]] == [1, 2]


@pytest.mark.django_db
def test_acts_can_be_marked_while_held_but_not_after_the_run_ends(show):
    client = client_for(show.owner)
    act(client, show.run, "hold", reason="Late house")
    assert act(client, show.run, "act-up").status_code == 200
    act(client, show.run, "end")
    assert act(client, show.run, "act-down").status_code == 409


@pytest.mark.django_db
def test_flagged_cues_mark_acts_when_they_fire(show):
    flag(show, "1", "up")
    flag(show, "12", "down")
    flag(show, "12.5", "up")
    client = client_for(show.owner)

    act(client, show.run, "go")  # Q1: Act 1 up
    assert act(client, show.run, "go").data["state"]["act"]["number"] == 1  # Q2: nothing to mark
    down = act(client, show.run, "go").data  # Q12: Act 1 down
    assert down["state"]["act"] is None
    q12 = CueEvent.objects.get(pk=down["event"]["id"])
    assert show.run.acts.get(number=1).down_at == q12.fired_at

    # BACK onto a flagged cue doesn't mark anything; a GOTO does.
    act(client, show.run, "go")  # Q12.5: Act 2 up
    act(client, show.run, "back")  # back to Q12, flagged down
    assert show.run.acts.get(number=2).down_at is None
    act(client, show.run, "goto", cue=show.cues["12"].id)
    assert show.run.acts.get(number=2).down_at is not None


@pytest.mark.django_db
def test_a_flagged_cue_does_nothing_when_there_is_nothing_to_mark(show):
    flag(show, "1", "down")
    flag(show, "2", "up")
    client = client_for(show.owner)
    act(client, show.run, "act-up")
    act(client, show.run, "goto", cue=show.cues["2"].id)  # up while Act 1 is up
    assert show.run.acts.count() == 1
    act(client, show.run, "act-down")
    act(client, show.run, "goto", cue=show.cues["1"].id)  # down with none up
    assert show.run.acts.count() == 1 and show.run.acts.get().down_at is not None


@pytest.mark.django_db
def test_a_console_fire_on_a_flagged_cue_marks_the_act(show):
    flag(show, "1", "up")
    services.go(show.run, show.cues["1"].id, source="console")
    assert show.run.acts.get().number == 1


@pytest.mark.django_db
def test_ending_the_run_brings_the_act_down(show):
    client = client_for(show.owner)
    act(client, show.run, "act-up")
    act(client, show.run, "end")
    show.run.refresh_from_db()
    assert show.run.acts.get().down_at == show.run.ended_at


@pytest.mark.django_db
def test_a_cue_takes_an_act_mark(show):
    client = client_for(show.owner)
    url = f"/api/cues/{show.cues['1'].id}/"
    assert client.patch(url, {"act_mark": "up"}, format="json").data["act_mark"] == "up"
    assert client.patch(url, {"act_mark": "sideways"}, format="json").status_code == 400
    assert client.patch(url, {"act_mark": ""}, format="json").data["act_mark"] == ""


# Correcting acts


@pytest.mark.django_db
def test_act_times_can_be_corrected_added_and_removed(show):
    client = client_for(show.owner)
    added = client.post(
        f"/api/runs/{show.run.id}/acts/", {"up_at": "2026-03-14T20:07:00Z", "down_at": "2026-03-14T21:15:00Z"}, format="json"
    )
    assert added.status_code == 201 and added.data["number"] == 1
    second = client.post(f"/api/runs/{show.run.id}/acts/", {"up_at": "2026-03-14T21:33:00Z"}, format="json").data
    assert second["number"] == 2 and second["down_at"] is None

    moved = client.patch(f"/api/acts/{second['id']}/", {"down_at": "2026-03-14T22:49:00Z"}, format="json")
    assert moved.status_code == 200 and moved.data["down_at"] == "2026-03-14T22:49:00Z"
    backwards = client.patch(f"/api/acts/{second['id']}/", {"down_at": "2026-03-14T21:00:00Z"}, format="json")
    assert backwards.status_code == 400
    assert backwards.data["down_at"] == ["An act can't come down before it goes up."]
    # The number is the act's place, not something to edit.
    client.patch(f"/api/acts/{second['id']}/", {"number": 7}, format="json")
    assert Act.objects.get(pk=second["id"]).number == 2

    assert client.delete(f"/api/acts/{added.data['id']}/").status_code == 204
    assert list(show.run.acts.values_list("number", flat=True)) == [2]


@pytest.mark.django_db
def test_acts_cant_overlap(show):
    first = Act.objects.create(run=show.run, number=1, up_at=at(20, 7), down_at=at(21, 15))
    second = Act.objects.create(run=show.run, number=2, up_at=at(21, 33), down_at=at(22, 49))
    client = client_for(show.owner)

    late = client.patch(f"/api/acts/{first.id}/", {"down_at": "2026-03-14T21:40:00Z"}, format="json")
    assert late.status_code == 400 and late.data["down_at"] == ["Act 2 is up by then."]
    # Still up (no down) while Act 2 is up isn't possible either.
    assert client.patch(f"/api/acts/{first.id}/", {"down_at": None}, format="json").status_code == 400
    early = client.patch(f"/api/acts/{second.id}/", {"up_at": "2026-03-14T21:00:00Z"}, format="json")
    assert early.status_code == 400 and early.data["up_at"] == ["Act 1 is still up then."]
    # A new act goes after the last one came down.
    added = client.post(f"/api/runs/{show.run.id}/acts/", {"up_at": "2026-03-14T22:30:00Z"}, format="json")
    assert added.status_code == 400 and added.data["up_at"] == ["Act 2 is still up then."]
    # Times that keep the order are fine.
    assert client.patch(f"/api/acts/{first.id}/", {"down_at": "2026-03-14T21:20:00Z"}, format="json").status_code == 200


@pytest.mark.django_db
def test_viewers_read_acts_and_strangers_see_nothing(show, make_user):
    act_row = Act.objects.create(run=show.run, number=1, up_at=at(20, 7))
    viewer = make_user("vic")
    Membership.objects.create(production=show.production, user=viewer, role="viewer")
    as_viewer = client_for(viewer)
    assert as_viewer.get(f"/api/runs/{show.run.id}/acts/").status_code == 200
    assert act(as_viewer, show.run, "act-down").status_code == 403
    assert as_viewer.patch(f"/api/acts/{act_row.id}/", {"down_at": None}, format="json").status_code == 403
    stranger = client_for(make_user("mallory"))
    assert stranger.delete(f"/api/acts/{act_row.id}/").status_code == 404


@pytest.mark.django_db
def test_acts_and_act_marks_come_through_a_backup(show):
    flag(show, "12", "down")
    Act.objects.create(run=show.run, number=1, up_at=at(20, 7), down_at=at(21, 15))
    Act.objects.create(run=show.run, number=2, up_at=at(21, 33))
    client = client_for(show.owner)
    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])

    fields = ("number", "up_at", "down_at")
    assert list(Act.objects.filter(run__production=copy).values_list(*fields)) == list(
        show.run.acts.values_list(*fields)
    )
    assert copy.cues.get(number=Decimal("12")).act_mark == "down"


# The report's times block


@pytest.fixture
def two_acts(show):
    """Act I 20:07–21:15 with a 6-minute hold, intermission 18 minutes, Act II 21:33–22:49."""
    run = show.run
    for action, fired_at, note in [("hold", at(20, 40), "Lost two movers"), ("resume", at(20, 46), "")]:
        event = CueEvent.objects.create(run=run, action=action, note=note)
        CueEvent.objects.filter(pk=event.pk).update(fired_at=fired_at)
    Act.objects.create(run=run, number=1, up_at=at(20, 7), down_at=at(21, 15, 57))
    Act.objects.create(run=run, number=2, up_at=at(21, 33, 57), down_at=at(22, 49, 37))
    Run.objects.filter(pk=run.pk).update(started_at=at(20, 7), ended_at=at(22, 50))
    run.refresh_from_db()
    return run


@pytest.mark.django_db
def test_the_report_gives_each_acts_times_and_the_totals(two_acts):
    block = report.build(two_acts)["acts"]
    assert [(a["number"], a["seconds"], a["held_seconds"], a["intermission_before_seconds"]) for a in block["items"]] == [
        (1, 68 * 60 + 57.0, 6 * 60.0, None),
        (2, 75 * 60 + 40.0, 0.0, 18 * 60.0),
    ]
    # 1:08:57 + 1:15:40, and 20:07 to 22:49:37.
    assert block["total_seconds"] == 2 * 3600 + 24 * 60 + 37.0
    assert block["show_seconds"] == 2 * 3600 + 42 * 60 + 37.0


@pytest.mark.django_db
def test_the_email_opens_with_the_times_block(two_acts):
    built = report.build(two_acts)
    text = report.as_text(built)
    assert (
        "ACTS\n"
        "  Act I up: 8:07\n"
        "  Act I down: 9:15\n"
        "  Act I total: 1:08:57 (held 6:00)\n"
        "  Intermission: 18:00\n"
        "  Act II up: 9:33\n"
        "  Act II down: 10:49\n"
        "  Act II total: 1:15:40\n"
        "  Total (without intermission): 2:24:37\n"
        "  Show total: 2:42:37\n"
    ) in text
    # Straight after the summary.
    assert text.index("Holds: ") < text.index("ACTS") < text.index("Report made")
    assert "<h2>Acts</h2>" in report.as_html(built)


@pytest.mark.django_db
def test_an_act_still_up_is_timed_so_far(show):
    Act.objects.create(run=show.run, number=1, up_at=at(20, 7))
    built = report.build(show.run, now=at(20, 37))
    assert built["acts"]["items"][0]["seconds"] == 30 * 60.0
    assert "  Act I down: –\n  Act I total: 30:00 so far\n" in report.as_text(built)


@pytest.mark.django_db
def test_a_run_with_no_acts_has_no_times_block(show):
    built = report.build(show.run)
    assert built["acts"] == {"items": [], "total_seconds": None, "show_seconds": None}
    assert "ACTS" not in report.as_text(built)
