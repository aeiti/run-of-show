"""The show report (report.py) and its endpoints: GET /runs/{id}/report/ and POST /runs/{id}/report/email/."""

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient
from rest_framework.throttling import ScopedRateThrottle

from shows import report
from shows.models import Cue, CueEvent, CueNote, Membership, Production, Run

CURTAIN = datetime(2026, 3, 14, 19, 30, tzinfo=timezone.utc)


def at(hour, minute):
    return datetime(2026, 3, 14, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def log(run, cues, rows):
    """Write events with explicit, distinct times: (action, cue number or None, time, note)."""
    for action, number, fired_at, note in rows:
        cue = cues.get(number)
        event = CueEvent.objects.create(
            run=run,
            action=action,
            cue=cue,
            cue_number=Decimal(number) if number else None,
            cue_label=cue.label if cue else "",
            note=note,
        )
        CueEvent.objects.filter(pk=event.pk).update(fired_at=fired_at)


@pytest.fixture
def show():
    """Preview 1 of Show A: three scenes, a hold before the start, one in a scene, and one never resumed.

    19:20 HOLD late house, 19:33 RESUME (all before the start)
    19:34 GO Q1 (Preshow, the start: 4 minutes late), 19:36 GO Q2
    19:40 GO Q5 (Lamp Room), 19:50 HOLD audience medical, 19:55 RESUME, 20:00 GO Q10
    20:10 GO Q20 (Wreck), 20:20 HOLD fly bar, never resumed; the run ended 20:30
    """
    User = get_user_model()
    owner = User.objects.create_user(username="alice", password="pw-for-tests", email="alice@example.com")
    production = Production.objects.create(
        owner=owner, name="Show A", company="Co", venue="Hall", opening_date=date(2026, 3, 14), closing_date=date(2026, 3, 28)
    )
    scenes = {"1": "Preshow", "5": "1.1 Lamp Room", "20": "1.2 Wreck"}
    cues = {
        n: Cue.objects.create(production=production, number=Decimal(n), label=f"Cue {n}", scene=scenes.get(n, ""))
        for n in ["1", "2", "5", "10", "20", "30"]
    }
    run = Run.objects.create(
        production=production, label="Preview 1", kind=Run.Kind.PREVIEW, notes="Patron fell in row F at 19:50."
    )
    log(
        run,
        cues,
        [
            ("hold", None, at(19, 20), "Late house"),
            ("resume", None, at(19, 33), ""),
            ("go", "1", at(19, 34), ""),
            ("go", "2", at(19, 36), ""),
            ("go", "5", at(19, 40), ""),
            ("hold", "5", at(19, 50), "Audience medical"),
            ("resume", "5", at(19, 55), ""),
            ("go", "10", at(20, 0), ""),
            ("go", "20", at(20, 10), ""),
            ("hold", "20", at(20, 20), "Fly bar stuck"),
        ],
    )
    Run.objects.filter(pk=run.pk).update(scheduled_start=CURTAIN, started_at=at(19, 34), ended_at=at(20, 30))
    for minute, number, text in [(45, "10", "Q10 late on the thunder"), (35, "2", "Q2 early")]:
        note = CueNote.objects.create(
            run=run, cue=cues[number], cue_number=cues[number].number, cue_label=cues[number].label, text=text, author=owner
        )
        CueNote.objects.filter(pk=note.pk).update(created_at=at(20, minute))
    run.refresh_from_db()
    return SimpleNamespace(owner=owner, production=production, cues=cues, run=run)


def member(show, username, role):
    user = get_user_model().objects.create_user(username=username, password="pw-for-tests")
    Membership.objects.create(production=show.production, user=user, role=role)
    return user


# The numbers


@pytest.mark.django_db
def test_report_times_and_holds(show):
    built = report.build(show.run)

    assert built["in_progress"] is False
    assert built["run"]["started_at"] == at(19, 34) and built["run"]["ended_at"] == at(20, 30)
    assert built["timing"] == {
        "late_seconds": 240.0,
        "running_seconds": 56 * 60.0,
        # The medical hold and the fly bar, not the late house before the start.
        "held_in_run_seconds": 15 * 60.0,
        "cues_fired": 5,
    }
    holds = built["holds"]
    assert holds["count"] == 3
    # 13 + 5 + 10 minutes: the hold never resumed lasts until the run ended.
    assert holds["total_seconds"] == 28 * 60.0
    assert [(h["reason"], h["seconds"], h["resumed_at"], h["cue_number"]) for h in holds["items"]] == [
        ("Late house", 13 * 60.0, at(19, 33), None),
        ("Audience medical", 5 * 60.0, at(19, 55), "5"),
        ("Fly bar stuck", 10 * 60.0, None, "20"),
    ]


@pytest.mark.django_db
def test_report_scene_lengths(show):
    scenes = report.build(show.run)["scenes"]
    assert [(s["name"], s["first_cue"], s["started_at"], s["seconds"], s["held_seconds"]) for s in scenes] == [
        ("Preshow", "1", at(19, 34), 6 * 60.0, 0.0),
        ("1.1 Lamp Room", "5", at(19, 40), 30 * 60.0, 5 * 60.0),
        ("1.2 Wreck", "20", at(20, 10), 20 * 60.0, 10 * 60.0),
    ]
    assert scenes[-1]["ended_at"] is None  # the last scene runs to the end of the run
    assert scenes[0]["ended_at"] == at(19, 40)


@pytest.mark.django_db
def test_report_notes_in_time_order(show):
    built = report.build(show.run)
    assert [(n["cue_number"], n["text"], n["author"]) for n in built["cue_notes"]] == [
        ("2", "Q2 early", "alice"),
        ("10", "Q10 late on the thunder", "alice"),
    ]
    assert built["notes"] == "Patron fell in row F at 19:50."


@pytest.mark.django_db
def test_scenes_count_deleted_cues_back_steps_and_cues_before_any_scene(show):
    run = Run.objects.create(production=show.production, label="Tech 1")
    # Q0.5 comes before the first scene; Q12 was deleted after the run, and was in the Lamp Room.
    Cue.objects.create(production=show.production, number=Decimal("0.5"), label="Walk-in")
    gone = Cue.objects.create(production=show.production, number=Decimal("12"), label="Cut")
    cues = {**show.cues, "0.5": show.production.cues.get(number=Decimal("0.5")), "12": gone}
    log(
        run,
        cues,
        [
            ("go", "0.5", at(14, 0), ""),
            ("goto", "12", at(14, 5), ""),
            ("go", "20", at(14, 7), ""),
            ("back", "12", at(14, 8), ""),
            ("reset", None, at(14, 9), ""),
            ("go", "20", at(14, 11), ""),
        ],
    )
    gone.delete()
    Run.objects.filter(pk=run.pk).update(started_at=at(14, 0), ended_at=at(14, 20))
    run.refresh_from_db()

    scenes = report.build(run)["scenes"]

    assert [(s["name"], s["seconds"]) for s in scenes] == [
        ("", 5 * 60.0),
        ("1.1 Lamp Room", 2 * 60.0),
        ("1.2 Wreck", 60.0),
        # BACK into the Lamp Room starts it again; the reset doesn't end it.
        ("1.1 Lamp Room", 3 * 60.0),
        ("1.2 Wreck", 9 * 60.0),
    ]


@pytest.mark.django_db
def test_a_run_in_progress_is_measured_up_to_now(show):
    run = Run.objects.create(production=show.production, label="Tonight")
    log(run, show.cues, [("go", "1", at(21, 0), ""), ("hold", "1", at(21, 10), "Rain")])
    Run.objects.filter(pk=run.pk).update(started_at=at(21, 0))
    run.refresh_from_db()

    built = report.build(run, now=at(21, 25))

    assert built["in_progress"] is True and built["as_of"] == at(21, 25)
    assert built["timing"]["running_seconds"] == 25 * 60.0
    assert built["holds"]["items"][0]["seconds"] == 15 * 60.0
    assert built["scenes"] == [
        {
            "name": "Preshow",
            "first_cue": "1",
            "started_at": at(21, 0),
            "ended_at": None,
            "seconds": 25 * 60.0,
            "held_seconds": 15 * 60.0,
        }
    ]


@pytest.mark.django_db
def test_a_run_that_never_started(show):
    run = Run.objects.create(production=show.production, label="Not yet", scheduled_start=CURTAIN)
    built = report.build(run)
    assert built["timing"] == {"late_seconds": None, "running_seconds": None, "held_in_run_seconds": None, "cues_fired": 0}
    assert built["holds"] == {"count": 0, "total_seconds": 0, "items": []}
    assert built["scenes"] == [] and built["cue_notes"] == []
    assert "Running time: –" in report.as_text(built)


# The endpoint and roles


@pytest.mark.django_db
def test_report_endpoint_returns_the_report_as_json(show):
    response = client_for(show.owner).get(f"/api/runs/{show.run.id}/report/")
    assert response.status_code == 200
    data = response.json()
    assert data["production"] == {
        "id": show.production.id,
        "name": "Show A",
        "company": "Co",
        "venue": "Hall",
        "opening_date": "2026-03-14",
        "closing_date": "2026-03-28",
    }
    assert data["run"]["scheduled_start"] == "2026-03-14T19:30:00Z"
    assert data["holds"]["total_seconds"] == 1680
    assert [s["name"] for s in data["scenes"]] == ["Preshow", "1.1 Lamp Room", "1.2 Wreck"]


@pytest.mark.django_db
def test_a_viewer_can_read_the_report_but_not_email_it(show):
    viewer = client_for(member(show, "vic", Membership.Role.VIEWER))
    assert viewer.get(f"/api/runs/{show.run.id}/report/").status_code == 200
    response = viewer.post(f"/api/runs/{show.run.id}/report/email/", {"to": ["sm@example.com"]}, format="json")
    assert response.status_code == 403
    assert mail.outbox == []


@pytest.mark.django_db
def test_an_operator_can_email_the_report(show):
    operator = client_for(member(show, "olive", Membership.Role.OPERATOR))
    response = operator.post(f"/api/runs/{show.run.id}/report/email/", {"to": ["sm@example.com"]}, format="json")
    assert response.status_code == 200
    assert len(mail.outbox) == 1


@pytest.mark.django_db
def test_strangers_and_anonymous_users_get_nothing(show):
    stranger = client_for(get_user_model().objects.create_user(username="eve", password="pw-for-tests"))
    assert stranger.get(f"/api/runs/{show.run.id}/report/").status_code == 404
    assert stranger.post(f"/api/runs/{show.run.id}/report/email/", {"to": ["a@example.com"]}, format="json").status_code == 404
    assert APIClient().get(f"/api/runs/{show.run.id}/report/").status_code == 401
    assert mail.outbox == []


# Email


@pytest.mark.django_db
def test_the_email_carries_the_report_as_text_and_html(show):
    Run.objects.filter(pk=show.run.pk).update(notes="Kid <script>alert(1)</script> in row F")
    response = client_for(show.owner).post(
        f"/api/runs/{show.run.id}/report/email/", {"to": ["sm@example.com", "lx@example.com"]}, format="json"
    )

    assert response.status_code == 200
    assert response.data == {"sent": 2, "to": ["sm@example.com", "lx@example.com"]}
    # One email each, so recipients don't see each other's addresses.
    assert [m.to for m in mail.outbox] == [["sm@example.com"], ["lx@example.com"]]
    message = mail.outbox[0]
    assert message.subject == "Show report: Show A, Preview 1"
    assert message.reply_to == ["alice@example.com"]
    text = message.body
    for expected in [
        "Co · Hall · 14 Mar 2026 – 28 Mar 2026",
        "Preview 1 (preview)",
        "Scheduled: Sat 14 Mar 2026, 19:30:00",
        "Started: Sat 14 Mar 2026, 19:34:00 (4:00 late)",
        "Ended: Sat 14 Mar 2026, 20:30:00",
        "Running time: 56:00",
        "Holds: 3, 28:00 in all",
        "  1.1 Lamp Room: 30:00 (held 5:00)",
        "  19:50:00  5:00  Audience medical (at Q5)",
        "  20:20:00  10:00, not resumed  Fly bar stuck (at Q20)",
        "  Q10 Cue 10: Q10 late on the thunder (alice)",
        "Kid <script>alert(1)</script> in row F",
    ]:
        assert expected in text, expected
    html, kind = message.alternatives[0]
    assert kind == "text/html"
    assert "<h2>Holds</h2>" in html and "Fly bar stuck" in html
    assert "<script>" not in html and "&lt;script&gt;" in html


@pytest.mark.django_db
@pytest.mark.parametrize(
    "to",
    [
        [],
        ["not-an-address"],
        ["ok@example.com", "bad@"],
        "sm@example.com",
        [f"crew{i}@example.com" for i in range(11)],
    ],
)
def test_recipients_are_validated(show, to):
    response = client_for(show.owner).post(f"/api/runs/{show.run.id}/report/email/", {"to": to}, format="json")
    assert response.status_code == 400
    assert "to" in response.data
    assert mail.outbox == []


@pytest.mark.django_db
def test_ten_recipients_is_the_limit_and_repeats_get_one_email(show):
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/report/email/"
    ten = [f"crew{i}@example.com" for i in range(10)]
    assert client.post(url, {"to": ten}, format="json").status_code == 200
    assert len(mail.outbox) == 10

    mail.outbox.clear()
    response = client.post(url, {"to": ["SM@example.com", "sm@example.com", "lx@example.com"]}, format="json")
    assert response.data == {"sent": 2, "to": ["SM@example.com", "lx@example.com"]}
    assert len(mail.outbox) == 2


@pytest.mark.django_db
def test_emailing_reports_is_rate_limited(show, monkeypatch):
    # DRF reads the rates once at import, so patch the class rather than settings.
    monkeypatch.setattr(ScopedRateThrottle, "THROTTLE_RATES", {"auth": "20/min", "report_email": "2/min"})
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/report/email/"
    statuses = [client.post(url, {"to": ["sm@example.com"]}, format="json").status_code for _ in range(3)]
    assert statuses == [200, 200, 429]
    assert len(mail.outbox) == 2
    # Reading the report isn't limited.
    assert client.get(f"/api/runs/{show.run.id}/report/").status_code == 200
