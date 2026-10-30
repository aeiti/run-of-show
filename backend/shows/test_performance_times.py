"""Opening and closing dates on a production; scheduled and actual start and end on a run."""

from datetime import date, datetime, timedelta, timezone

import pytest
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from rest_framework.test import APIClient

from shows.models import CueEvent, Membership, Production, Run

CURTAIN = datetime(2026, 3, 14, 19, 30, tzinfo=timezone.utc)


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def act(client, run, action, **body):
    return client.post(f"/api/runs/{run.id}/{action}/", body, format="json")


def iso(value):
    return value.isoformat().replace("+00:00", "Z")


def patch_run(client, run, **body):
    return client.patch(f"/api/runs/{run.id}/", body, format="json")


# Production dates


@pytest.mark.django_db
def test_a_production_has_optional_opening_and_closing_dates(make_user):
    client = client_for(make_user("alice"))
    created = client.post(
        "/api/productions/", {"name": "Show", "opening_date": "2026-11-14", "closing_date": "2026-11-29"}, format="json"
    )
    assert created.status_code == 201
    assert (created.data["opening_date"], created.data["closing_date"]) == ("2026-11-14", "2026-11-29")
    assert "performance_date" not in created.data

    neither = client.post("/api/productions/", {"name": "Other"}, format="json")
    assert neither.status_code == 201
    assert (neither.data["opening_date"], neither.data["closing_date"]) == (None, None)

    # A one-night show opens and closes on the same day.
    one_night = client.post(
        "/api/productions/", {"name": "Gala", "opening_date": "2026-12-01", "closing_date": "2026-12-01"}, format="json"
    )
    assert one_night.status_code == 201


@pytest.mark.django_db
def test_closing_before_opening_is_refused(make_user):
    client = client_for(make_user("alice"))
    response = client.post(
        "/api/productions/", {"name": "Show", "opening_date": "2026-11-14", "closing_date": "2026-11-13"}, format="json"
    )
    assert response.status_code == 400
    assert response.data["closing_date"] == ["The closing date can't be before the opening date."]
    assert not Production.objects.exists()


@pytest.mark.django_db
def test_a_patch_is_checked_against_the_saved_date(show):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/"
    assert client.patch(url, {"opening_date": "2026-11-14"}, format="json").status_code == 200

    early = client.patch(url, {"closing_date": "2026-11-01"}, format="json")
    assert early.status_code == 400
    assert "closing_date" in early.data
    late_opening = client.patch(url, {"closing_date": "2026-11-29"}, format="json")
    assert late_opening.status_code == 200
    assert client.patch(url, {"opening_date": "2026-12-01"}, format="json").status_code == 400

    show.production.refresh_from_db()
    assert (show.production.opening_date, show.production.closing_date) == (date(2026, 11, 14), date(2026, 11, 29))


# Migration 0012


@pytest.mark.django_db(transaction=True)
def test_migration_moves_the_performance_date_to_opening_and_backfills_starts():
    before, after = [("shows", "0011_performance_times")], [("shows", "0012_backfill_performance_times")]
    executor = MigrationExecutor(connection)
    leaf = executor.loader.graph.leaf_nodes()
    try:
        executor.migrate(before)
        apps = executor.loader.project_state(before).apps
        User = apps.get_model("auth", "User")
        Production = apps.get_model("shows", "Production")
        Run = apps.get_model("shows", "Run")
        CueEvent = apps.get_model("shows", "CueEvent")

        owner = User.objects.create(username="alice")
        dated = Production.objects.create(owner=owner, name="Dated", performance_date=date(2026, 3, 14))
        undated = Production.objects.create(owner=owner, name="Undated")
        played = Run.objects.create(production=dated, label="Played")
        held_first = Run.objects.create(production=dated, label="Held first")
        untouched = Run.objects.create(production=dated, label="Nothing fired")
        for run, action, at in [
            (played, "go", CURTAIN),
            (played, "go", CURTAIN + timedelta(minutes=3)),
            (held_first, "hold", CURTAIN - timedelta(minutes=10)),
            (held_first, "resume", CURTAIN - timedelta(minutes=2)),
            (held_first, "goto", CURTAIN + timedelta(minutes=1)),
            (untouched, "hold", CURTAIN),
        ]:
            event = CueEvent.objects.create(run=run, action=action)
            CueEvent.objects.filter(pk=event.pk).update(fired_at=at)

        executor = MigrationExecutor(connection)
        executor.migrate(after)
        apps = executor.loader.project_state(after).apps
        Production = apps.get_model("shows", "Production")
        Run = apps.get_model("shows", "Run")

        assert Production.objects.get(pk=dated.pk).opening_date == date(2026, 3, 14)
        assert Production.objects.get(pk=dated.pk).closing_date is None
        assert Production.objects.get(pk=undated.pk).opening_date is None
        starts = dict(Run.objects.values_list("label", "started_at"))
        assert starts == {"Played": CURTAIN, "Held first": CURTAIN + timedelta(minutes=1), "Nothing fired": None}
    finally:
        executor = MigrationExecutor(connection)
        executor.migrate(leaf)


# The actual start


@pytest.mark.django_db
def test_the_first_go_records_the_start(show):
    client = client_for(show.owner)
    assert client.get(f"/api/runs/{show.run.id}/").data["started_at"] is None

    fired = act(client, show.run, "go")

    show.run.refresh_from_db()
    assert show.run.started_at is not None
    assert iso(show.run.started_at) == fired.data["event"]["fired_at"]
    assert client.get(f"/api/runs/{show.run.id}/").data["started_at"] == fired.data["event"]["fired_at"]


@pytest.mark.django_db
def test_a_goto_also_starts_the_run(show):
    act(client_for(show.owner), show.run, "goto", cue=show.cues["12"].id)
    show.run.refresh_from_db()
    assert show.run.started_at == CueEvent.objects.get().fired_at


@pytest.mark.django_db
def test_a_hold_or_reset_does_not_start_the_run(show):
    client = client_for(show.owner)
    act(client, show.run, "hold", reason="Late house")
    act(client, show.run, "resume")
    act(client, show.run, "reset")
    show.run.refresh_from_db()
    assert show.run.started_at is None

    act(client, show.run, "go")
    show.run.refresh_from_db()
    assert show.run.started_at == CueEvent.objects.get(action="go").fired_at


@pytest.mark.django_db
def test_a_start_already_set_is_kept(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    Run.objects.filter(pk=show.run.pk).update(started_at=CURTAIN)

    act(client, show.run, "go")
    act(client, show.run, "goto", cue=show.cues["100"].id)

    show.run.refresh_from_db()
    assert show.run.started_at == CURTAIN


@pytest.mark.django_db
def test_a_start_set_before_the_first_go_is_kept(show):
    client = client_for(show.owner)
    assert patch_run(client, show.run, started_at=iso(CURTAIN)).status_code == 200
    act(client, show.run, "go")
    show.run.refresh_from_db()
    assert show.run.started_at == CURTAIN


# Scheduled start and corrections


@pytest.mark.django_db
def test_a_new_run_can_have_a_scheduled_start_but_not_an_actual_one(show):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/runs/"
    created = client.post(url, {"label": "Opening", "kind": "performance", "scheduled_start": iso(CURTAIN)}, format="json")
    assert created.status_code == 201
    assert created.data["scheduled_start"] == iso(CURTAIN)
    assert (created.data["started_at"], created.data["ended_at"]) == (None, None)

    started = client.post(url, {"label": "Two", "started_at": iso(CURTAIN)}, format="json")
    assert started.status_code == 400
    assert "started_at" in started.data
    ended = client.post(url, {"label": "Three", "ended_at": iso(CURTAIN)}, format="json")
    assert ended.status_code == 400
    assert "ended_at" in ended.data


@pytest.mark.django_db
def test_an_operator_corrects_the_times_after_the_run(show, make_user):
    operator = make_user("olive")
    Membership.objects.create(production=show.production, user=operator, role=Membership.Role.OPERATOR)
    client = client_for(operator)
    act(client, show.run, "go")
    act(client, show.run, "end")

    response = patch_run(
        client,
        show.run,
        scheduled_start=iso(CURTAIN),
        started_at=iso(CURTAIN + timedelta(minutes=4)),
        ended_at=iso(CURTAIN + timedelta(hours=2, minutes=10)),
    )

    assert response.status_code == 200
    show.run.refresh_from_db()
    assert show.run.scheduled_start == CURTAIN
    assert show.run.started_at == CURTAIN + timedelta(minutes=4)
    assert show.run.ended_at == CURTAIN + timedelta(hours=2, minutes=10)
    # Clearing the scheduled start is fine.
    assert patch_run(client, show.run, scheduled_start=None).status_code == 200


@pytest.mark.django_db
def test_an_end_before_the_start_is_refused(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    act(client, show.run, "end")
    Run.objects.filter(pk=show.run.pk).update(started_at=CURTAIN, ended_at=CURTAIN + timedelta(hours=2))

    both = patch_run(client, show.run, started_at=iso(CURTAIN), ended_at=iso(CURTAIN - timedelta(seconds=1)))
    assert both.status_code == 400
    assert both.data["ended_at"] == ["A run can't end before it starts."]
    # Against the saved value when only one side is sent.
    assert patch_run(client, show.run, ended_at=iso(CURTAIN - timedelta(minutes=1))).status_code == 400
    assert patch_run(client, show.run, started_at=iso(CURTAIN + timedelta(hours=3))).status_code == 400
    # Equal is allowed.
    assert patch_run(client, show.run, ended_at=iso(CURTAIN)).status_code == 200

    show.run.refresh_from_db()
    assert (show.run.started_at, show.run.ended_at) == (CURTAIN, CURTAIN)


@pytest.mark.django_db
def test_ending_and_reopening_go_through_end_run_only(show):
    client = client_for(show.owner)
    act(client, show.run, "go")
    live = patch_run(client, show.run, ended_at=iso(CURTAIN + timedelta(days=400)))
    assert live.status_code == 400
    assert live.data["ended_at"] == ["Use End run to end a run."]
    show.run.refresh_from_db()
    assert show.run.ended_at is None

    act(client, show.run, "end")
    reopen = patch_run(client, show.run, ended_at=None)
    assert reopen.status_code == 400
    assert reopen.data["ended_at"] == ["An ended run can't be reopened."]


@pytest.mark.django_db
def test_a_viewer_cannot_change_the_times(show, make_user):
    viewer = make_user("vic")
    Membership.objects.create(production=show.production, user=viewer, role=Membership.Role.VIEWER)
    assert patch_run(client_for(viewer), show.run, scheduled_start=iso(CURTAIN)).status_code == 403
    assert patch_run(client_for(make_user("stranger")), show.run, scheduled_start=iso(CURTAIN)).status_code == 404
    show.run.refresh_from_db()
    assert show.run.scheduled_start is None


# Backups


def v1_file():
    """A version 1 production file, as exported before opening and closing dates."""
    return {
        "format": "run-of-show/production",
        "version": 1,
        "production": {"name": "Old", "company": "", "venue": "Hall", "performance_date": "2026-03-14", "notes": ""},
        "cues": [{"number": "1", "label": "Open"}],
        "runs": [
            {
                "label": "Preview 1",
                "kind": "preview",
                "created_at": iso(CURTAIN - timedelta(hours=1)),
                "ended_at": iso(CURTAIN + timedelta(hours=2)),
                "notes": "",
                "events": [
                    {"action": "hold", "cue": None, "cue_number": None, "fired_at": iso(CURTAIN - timedelta(minutes=5)), "note": "House"},
                    {"action": "resume", "cue": None, "cue_number": None, "fired_at": iso(CURTAIN - timedelta(minutes=1))},
                    {"action": "go", "cue": "1", "cue_number": "1", "cue_label": "Open", "fired_at": iso(CURTAIN)},
                ],
            }
        ],
    }


@pytest.mark.django_db
def test_a_version_1_file_imports_with_its_date_as_the_opening(make_user):
    client = client_for(make_user("alice"))
    response = client.post("/api/productions/import/", v1_file(), format="json")
    assert response.status_code == 201
    assert (response.data["opening_date"], response.data["closing_date"]) == ("2026-03-14", None)

    run = Run.objects.get(production_id=response.data["id"])
    # No start in the file: it was the first GO, not the hold before it.
    assert run.started_at == CURTAIN
    assert run.scheduled_start is None


@pytest.mark.django_db
def test_an_export_is_version_2_and_carries_the_times(show):
    Production.objects.filter(pk=show.production.pk).update(opening_date=date(2026, 3, 14), closing_date=date(2026, 3, 28))
    Run.objects.filter(pk=show.run.pk).update(
        scheduled_start=CURTAIN, started_at=CURTAIN + timedelta(minutes=3), ended_at=CURTAIN + timedelta(hours=2)
    )
    data = client_for(show.owner).get(f"/api/productions/{show.production.id}/export/").json()
    assert data["version"] == 2
    assert data["production"]["opening_date"] == "2026-03-14" and data["production"]["closing_date"] == "2026-03-28"
    assert "performance_date" not in data["production"]
    run = data["runs"][0]
    assert run["scheduled_start"] == iso(CURTAIN)
    assert run["started_at"] == iso(CURTAIN + timedelta(minutes=3))


@pytest.mark.django_db
def test_an_import_with_dates_or_times_out_of_order_is_refused(make_user):
    client = client_for(make_user("alice"))
    dates = {**v1_file(), "version": 2}
    dates["production"] = {"name": "Old", "opening_date": "2026-03-14", "closing_date": "2026-03-01"}
    assert client.post("/api/productions/import/", dates, format="json").status_code == 400

    times = {**v1_file(), "version": 2, "production": {"name": "Old"}}
    times["runs"] = [{**times["runs"][0], "started_at": iso(CURTAIN + timedelta(hours=3))}]
    assert client.post("/api/productions/import/", times, format="json").status_code == 400
    assert not Production.objects.exists()
