"""The report's header, performance numbers, next call, stage managers, contacts and attachments (#71)."""

import json
from datetime import datetime, timedelta, timezone

import pytest
from django.core import mail
from django.core.cache import cache
from django.core.files.base import ContentFile
from rest_framework.test import APIClient

from shows import report
from shows.models import Membership, Production, ProductionFile, Run


def at(day, hour, minute=0):
    return datetime(2026, 3, day, hour, minute, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def fresh_throttles():
    cache.clear()


def client_for(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


def run(show, label, kind, start, **fields):
    return Run.objects.create(production=show.production, label=label, kind=kind, scheduled_start=start, **fields)


@pytest.fixture
def week(show):
    """Three previews, then performances: two on Saturday the 7th (matinee and evening), one on Sunday."""
    show.run.delete()
    runs = {
        "p1": run(show, "Preview 1", "preview", at(3, 20)),
        "p2": run(show, "Preview 2", "preview", at(4, 20)),
        "p3": run(show, "Preview 3", "preview", at(5, 20)),
        "open": run(show, "Opening", "performance", at(6, 19, 30), special_label="Opening Night"),
        "sat_mat": run(show, "Sat mat", "performance", at(7, 14)),
        "sat_eve": run(show, "Sat eve", "performance", at(7, 20)),
        "tech": run(show, "Tech", "tech", at(2, 12)),
    }
    return runs


def build(r):
    return report.build(Run.objects.get(pk=r.pk))


# Numbers and the header


@pytest.mark.django_db
def test_performances_and_previews_are_counted_apart_in_date_order(week):
    headers = {key: build(r)["header"] for key, r in week.items()}
    assert [headers[k]["number"] for k in ("p1", "p2", "p3", "open", "sat_mat", "sat_eve")] == [1, 2, 3, 1, 2, 3]
    assert headers["tech"]["number"] is None
    assert headers["p2"]["title"] == "Evening Preview #2"
    assert headers["sat_mat"]["line"] == "Matinee Performance #2 · Saturday, March 7, 2026 @ 2:00pm"
    assert headers["open"]["line"] == "Evening Performance #1 · Friday, March 6, 2026 @ 7:30pm"
    assert headers["open"]["special_label"] == "Opening Night"
    # Other kinds are named by kind, with no session or number.
    assert headers["tech"]["line"] == "Tech · Monday, March 2, 2026 @ 12:00pm"


@pytest.mark.django_db
def test_a_number_set_by_hand_resets_the_count(week):
    Run.objects.filter(pk=week["open"].pk).update(performance_number=10)
    assert [build(week[k])["header"]["number"] for k in ("open", "sat_mat", "sat_eve")] == [10, 11, 12]
    # Previews keep their own count.
    assert build(week["p3"])["header"]["number"] == 3


@pytest.mark.django_db
def test_a_run_with_no_scheduled_start_is_dated_by_when_it_started(show):
    Run.objects.filter(pk=show.run.pk).update(kind="performance", started_at=at(9, 19, 45))
    header = build(show.run)["header"]
    assert header["line"] == "Evening Performance #1 · Monday, March 9, 2026 @ 7:45pm"


@pytest.mark.django_db
def test_the_subject_is_named_by_kind_and_date(week):
    assert report.subject(build(week["sat_eve"])) == "Show A Performance Report Saturday, March 7, 2026"
    assert report.subject(build(week["tech"])) == "Show A Tech Report Monday, March 2, 2026"


# The next call


@pytest.mark.django_db
def test_the_next_call_comes_from_the_next_scheduled_run_and_the_template(week, show):
    Production.objects.filter(pk=show.production.pk).update(
        call_template=[{"minutes": 30, "label": "Half hour – House open"}, {"minutes": 45, "label": "Wig prep starts"}]
    )
    # Friday's opening is followed by a two-show Saturday.
    assert build(week["open"])["next_call"] == {
        "text": "Saturday, March 7, 2026\n(2 Performances, First Call)\n"
        "1:15pm  Wig prep starts\n1:30pm  Half hour – House open\n2:00pm  Performance #2",
        "generated": "Saturday, March 7, 2026\n(2 Performances, First Call)\n"
        "1:15pm  Wig prep starts\n1:30pm  Half hour – House open\n2:00pm  Performance #2",
        "edited": False,
    }
    # The preview before opening calls opening night, with its label.
    assert build(week["p3"])["next_call"]["text"].endswith("7:30pm  Performance #1 – Opening Night")
    # Nothing scheduled after the last run.
    assert build(week["sat_eve"])["next_call"] == {"text": "", "generated": "", "edited": False}


@pytest.mark.django_db
def test_the_default_template_is_half_hour(week):
    assert build(week["p1"])["next_call"]["text"] == (
        "Wednesday, March 4, 2026\n7:30pm  Half hour – House open\n8:00pm  Preview #2"
    )


@pytest.mark.django_db
def test_a_next_call_written_on_the_run_replaces_the_generated_one(week):
    client = client_for(week["p1"].production.owner)
    saved = client.patch(f"/api/runs/{week['p1'].id}/", {"next_call": "TBA – see the schedule"}, format="json")
    assert saved.status_code == 200
    call = build(week["p1"])["next_call"]
    assert (call["text"], call["edited"]) == ("TBA – see the schedule", True)
    assert call["generated"].startswith("Wednesday, March 4, 2026")
    # Clearing it goes back to the generated call.
    client.patch(f"/api/runs/{week['p1'].id}/", {"next_call": ""}, format="json")
    assert build(week["p1"])["next_call"]["edited"] is False


# Stage managers and contacts


@pytest.mark.django_db
def test_stage_managers_carry_over_from_the_previous_run(week):
    Run.objects.filter(pk=week["p2"].pk).update(stage_managers="David S. Franklin, Alyssa Escalante")
    assert build(week["p2"])["stage_managers"] == {"names": "David S. Franklin, Alyssa Escalante", "inherited": False}
    assert build(week["p3"])["stage_managers"] == {"names": "David S. Franklin, Alyssa Escalante", "inherited": True}
    assert build(week["p1"])["stage_managers"] == {"names": "", "inherited": False}
    Run.objects.filter(pk=week["open"].pk).update(stage_managers="Gaby Ostrove")
    assert build(week["sat_mat"])["stage_managers"]["names"] == "Gaby Ostrove"


@pytest.mark.django_db
def test_the_email_has_the_header_next_call_and_sign_off(week, show):
    Production.objects.filter(pk=show.production.pk).update(contacts="PSM: David S. Franklin, 555-0100")
    Run.objects.filter(pk=week["open"].pk).update(stage_managers="David S. Franklin")
    built = build(week["open"])
    text = report.as_text(built)
    for expected in [
        "Show A Performance Report Friday, March 6, 2026\n",
        "Evening Performance #1 · Friday, March 6, 2026 @ 7:30pm\nOpening Night\n",
        "NEXT CALL\nSaturday, March 7, 2026\n(2 Performances, First Call)\n",
        "Stage managers: David S. Franklin\n",
        "PSM: David S. Franklin, 555-0100\n",
    ]:
        assert expected in text, expected
    assert text.index("NEXT CALL") < text.index("Stage managers") < text.index("PSM:") < text.index("Report made")
    html = report.as_html(built)
    assert "<h2>Next call</h2>" in html and "<b>Opening Night</b>" in html


@pytest.mark.django_db
def test_header_fields_are_edited_by_operators_and_validated(week, make_user):
    operator = make_user("olive")
    Membership.objects.create(production=week["p1"].production, user=operator, role="operator")
    url = f"/api/runs/{week['p1'].id}/"
    body = {"performance_number": 4, "special_label": "Press night", "stage_managers": "Olive"}
    saved = client_for(operator).patch(url, body, format="json")
    assert saved.status_code == 200
    assert {k: saved.data[k] for k in body} == body
    assert client_for(operator).patch(url, {"performance_number": 0}, format="json").status_code == 400
    viewer = make_user("vic")
    Membership.objects.create(production=week["p1"].production, user=viewer, role="viewer")
    assert client_for(viewer).patch(url, {"special_label": "x"}, format="json").status_code == 403


@pytest.mark.django_db
def test_the_call_template_and_contacts_are_production_settings(show):
    client = client_for(show.owner)
    url = f"/api/productions/{show.production.id}/"
    assert client.get(url).data["call_template"] == [{"minutes": 30, "label": "Half hour – House open"}]
    calls = [{"minutes": 90, "label": "Crew call"}, {"minutes": 30, "label": "Half hour"}]
    saved = client.patch(url, {"call_template": calls, "contacts": "PSM: Alice"}, format="json")
    assert saved.status_code == 200
    assert (saved.data["call_template"], saved.data["contacts"]) == (calls, "PSM: Alice")
    bad = client.patch(url, {"call_template": [{"minutes": -5, "label": "Before"}]}, format="json")
    assert bad.status_code == 400


@pytest.mark.django_db
def test_header_settings_come_through_a_backup(week, show):
    Production.objects.filter(pk=show.production.pk).update(
        call_template=[{"minutes": 45, "label": "Wig prep"}], contacts="PSM: Alice"
    )
    Run.objects.filter(pk=week["open"].pk).update(
        performance_number=10, stage_managers="Alice", next_call="Sunday 2pm"
    )
    client = client_for(show.owner)
    data = json.loads(client.get(f"/api/productions/{show.production.id}/export/").content)
    copy = Production.objects.get(pk=client.post("/api/productions/import/", data, format="json").data["id"])
    assert (copy.calls, copy.contacts) == ([{"minutes": 45, "label": "Wig prep"}], "PSM: Alice")
    fields = ("label", "performance_number", "special_label", "stage_managers", "next_call")
    assert sorted(copy.runs.values_list(*fields)) == sorted(show.production.runs.values_list(*fields))


# Attachments


def upload(production, name, data, content_type="application/pdf"):
    row = ProductionFile(production=production, kind="other", name=name, version=1, size=len(data), content_type=content_type)
    row.file.save(name, ContentFile(data), save=False)
    row.save()
    return row


@pytest.mark.django_db
def test_production_files_can_be_attached_to_the_email(show, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    schedule = upload(show.production, "week.pdf", b"%PDF-1.4 schedule")
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/report/email/"
    sent = client.post(url, {"to": ["sm@example.com"], "files": [schedule.id]}, format="json")
    assert sent.status_code == 200
    assert mail.outbox[0].attachments == [("week.pdf", b"%PDF-1.4 schedule", "application/pdf")]


@pytest.mark.django_db
def test_attachments_must_be_this_productions_and_not_too_big(show, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    other = Production.objects.create(owner=show.owner, name="Other")
    theirs = upload(other, "theirs.pdf", b"x")
    client = client_for(show.owner)
    url = f"/api/runs/{show.run.id}/report/email/"
    wrong = client.post(url, {"to": ["sm@example.com"], "files": [theirs.id]}, format="json")
    assert wrong.status_code == 400 and wrong.data["files"] == ["That file is not in this production."]

    settings.REPORT_ATTACHMENTS_MAX_SIZE = 1024 * 1024
    big = upload(show.production, "big.pdf", b"x" * (1024 * 1024 + 1))
    too_big = client.post(url, {"to": ["sm@example.com"], "files": [big.id]}, format="json")
    assert too_big.status_code == 400 and too_big.data["files"] == ["Attachments can come to 1 MB at most."]
    assert mail.outbox == []
