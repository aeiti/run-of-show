"""The combined report for a two-show day: report.build_day, GET /runs/{id}/report/day/ and the email."""

from datetime import datetime, timezone

import pytest
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.cache import cache
from rest_framework.test import APIClient

from shows import report
from shows.models import Act, CueNote, Production, Run


def at(day, hour, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def add_run(production, label, kind, curtain, **fields):
    return Run.objects.create(production=production, label=label, kind=kind, scheduled_start=curtain, **fields)


def add_note(run, text, section="", moment=None):
    return CueNote.objects.create(run=run, text=text, section=section, at=moment)


@pytest.fixture
def day():
    """Two performances on 14 March (a 2pm matinee and an 8pm evening), one the day before, and a tech that day."""
    owner = get_user_model().objects.create_user(username="alice", password="pw-for-tests", email="alice@example.com")
    production = Production.objects.create(owner=owner, name="Amadeus", note_sections=["Performance", "Tech", "Venue"])
    before = add_run(production, "Perf 29", Run.Kind.PERFORMANCE, at(13, 20), performance_number=29)
    matinee = add_run(production, "Sat mat", Run.Kind.PERFORMANCE, at(14, 14), stage_managers="David, Alyssa")
    evening = add_run(production, "Sat eve", Run.Kind.PERFORMANCE, at(14, 20), stage_managers="David, Alyssa")
    tech = add_run(production, "Spot tech", Run.Kind.TECH, at(14, 10))
    add_run(production, "Sun mat", Run.Kind.PERFORMANCE, at(15, 14))
    Act.objects.create(run=matinee, number=1, up_at=at(14, 14, 3), down_at=at(14, 15, 10))
    Act.objects.create(run=evening, number=1, up_at=at(14, 20, 5), down_at=at(14, 21, 15))
    add_note(matinee, "Big laugh on the bell", "Performance")
    add_note(evening, "Standing ovation", "Performance")
    add_note(evening, "Turntable #5 missed", "Tech")
    add_note(matinee, "Usher thanked the crew")  # no section: General
    return type("Day", (), {
        "owner": owner, "production": production, "before": before, "matinee": matinee, "evening": evening, "tech": tech,
    })


@pytest.mark.django_db
def test_a_day_is_the_performances_and_previews_on_that_date(day):
    runs = list(day.production.runs.all())
    assert report.same_day(day.evening, runs) == [day.matinee, day.evening]
    # A tech that day keeps its own report.
    assert report.same_day(day.tech, runs) == [day.tech]
    # A single show's report says which shows share its day, and the setting.
    built = report.build(day.matinee)
    assert built["day"] == {
        "shows": [
            {"id": day.matinee.id, "title": "Matinee Performance #30"},
            {"id": day.evening.id, "title": "Evening Performance #31"},
        ],
        "combined": True,
    }
    assert report.build(day.before)["day"] is None


@pytest.mark.django_db
def test_the_combined_report_keeps_each_shows_times_and_notes(day):
    built = report.build_day([day.matinee, day.evening])
    assert built["title"] == "Performance #30 & 31"
    assert built["date"] == "Saturday, March 14, 2026"
    assert [show["run"]["id"] for show in built["shows"]] == [day.matinee.id, day.evening.id]
    assert [show["acts"]["items"][0]["seconds"] for show in built["shows"]] == [67 * 60.0, 70 * 60.0]
    # One next call (the evening's: Sunday's matinee) and one sign-off.
    assert built["next_call"]["text"].startswith("Sunday, March 15, 2026")
    assert built["stage_managers"] == "David, Alyssa"

    sections = {name: [[n["text"] for n in notes] for _, notes in entries] for name, entries in report.day_sections(built)}
    assert sections == {
        "Performance": [["Big laugh on the bell"], ["Standing ovation"]],
        "Tech": [[], ["Turntable #5 missed"]],
        "Venue": [[], []],
        "General": [["Usher thanked the crew"], []],
    }


@pytest.mark.django_db
def test_the_combined_email_text(day):
    text = report.as_text_day(report.build_day([day.matinee, day.evening]))
    assert text.startswith("Amadeus Performance Report Saturday, March 14, 2026\n")
    assert "Performance #30 & 31 · Saturday, March 14, 2026\n" in text
    assert "MATINEE PERFORMANCE #30\n" in text and "EVENING PERFORMANCE #31\n" in text
    assert "  Act I total: 1:07:00\n" in text
    # The header has the date, so the shows' times are times of day.
    assert "  Scheduled: 2:00pm\n" in text and "  Scheduled: 8:00pm\n" in text
    # A section with notes from one show gives the other "None"; one with none from either, one line.
    assert (
        "TECH\n"
        "  Matinee Performance #30:\n"
        "    None.\n"
        "  Evening Performance #31:\n"
        "    - Turntable #5 missed\n"
    ) in text
    assert "VENUE\n  Nothing to report.\n" in text
    assert text.count("NEXT CALL") == 1


@pytest.mark.django_db
def test_the_combined_html_puts_the_times_side_by_side(day):
    built = report.build_day([day.matinee, day.evening])
    html = report.as_html_day(built)
    assert "<th align='left'>Matinee Performance #30</th><th align='left'>Evening Performance #31</th>" in html
    rows = dict(report.times_table(built))
    assert rows["Act I total"] == ["1:07:00", "1:10:00"]
    assert "<h2>Venue</h2><p>Nothing to report.</p>" in html
    assert "<p><i>Matinee Performance #30:</i> None.</p>" in html


@pytest.mark.django_db
def test_different_stage_managers_are_named_per_show(day):
    Run.objects.filter(pk=day.evening.pk).update(stage_managers="Gaby")
    built = report.build_day([day.matinee, Run.objects.get(pk=day.evening.pk)])
    assert built["stage_managers"] == "Matinee Performance #30: David, Alyssa; Evening Performance #31: Gaby"


@pytest.mark.django_db
def test_the_day_report_endpoint(day, make_user):
    client = client_for(day.owner)
    data = client.get(f"/api/runs/{day.evening.id}/report/day/").json()
    assert data["title"] == "Performance #30 & 31"
    assert [show["run"]["id"] for show in data["shows"]] == [day.matinee.id, day.evening.id]
    stranger = client_for(make_user("mallory"))
    assert stranger.get(f"/api/runs/{day.evening.id}/report/day/").status_code == 404


@pytest.mark.django_db
def test_the_email_follows_the_productions_setting_unless_told(day):
    client = client_for(day.owner)
    url = f"/api/runs/{day.evening.id}/report/email/"
    client.post(url, {"to": ["sm@example.com"]}, format="json")
    assert "Performance #30 & 31" in mail.outbox[-1].body

    client.post(url, {"to": ["sm@example.com"], "scope": "show"}, format="json")
    assert "Performance #30 & 31" not in mail.outbox[-1].body
    assert "Evening Performance #31" in mail.outbox[-1].body

    client.patch(f"/api/productions/{day.production.id}/", {"combined_reports": False}, format="json")
    client.post(url, {"to": ["sm@example.com"]}, format="json")
    assert "Performance #30 & 31" not in mail.outbox[-1].body
    client.post(url, {"to": ["sm@example.com"], "scope": "day"}, format="json")
    assert "Performance #30 & 31" in mail.outbox[-1].body

    # A show alone on its day always gets its own report.
    client.post(f"/api/runs/{day.before.id}/report/email/", {"to": ["sm@example.com"], "scope": "day"}, format="json")
    assert "Performance #29" in mail.outbox[-1].body and " & " not in mail.outbox[-1].subject


@pytest.mark.django_db
def test_the_setting_comes_through_a_backup(day):
    client = client_for(day.owner)
    client.patch(f"/api/productions/{day.production.id}/", {"combined_reports": False}, format="json")
    data = client.get(f"/api/productions/{day.production.id}/export/").json()
    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])
    assert copy.combined_reports is False
