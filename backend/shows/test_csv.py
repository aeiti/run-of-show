import csv
import io
from datetime import timedelta
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from shows import csv_io
from shows.models import Cue, CueEvent, Production, Run

# The shape of an ETC Eos CSV export: a section before TARGETS (whose header
# differs), Cue_List rows, cues in two lists with the same numbers, a part
# row, a point cue, label / notes / scene text, and cue timing as in a real
# show file: a part cue has a blank time and Eos's total as its duration, and
# times of a minute or more are written m:ss.
TARGETS_HEADER = (
    "TARGET_TYPE,TARGET_TYPE_AS_TEXT,TARGET_LIST_NUMBER,TARGET_ID,TARGET_DCID,PART_NUMBER,LABEL,"
    "TIME_DATA,UP_DELAY,DOWN_TIME,DOWN_DELAY,FOCUS_TIME,FOCUS_DELAY,COLOR_TIME,COLOR_DELAY,BEAM_TIME,"
    "BEAM_DELAY,DURATION,ALERT_TIME,MARK,BLOCK,ASSERT,ALL_FADE,PREHEAT,FOLLOW,LINK,LOOP,CURVE,RATE,"
    "EXTERNAL_LINKS,EFFECTS,MODE,CUE_NOTES,SCENE_TEXT,SCENE_END,WIDTH,HEIGHT"
)


def eos_row(kind, list_no, cue, part="", label="", notes="", scene="", time="", down="", duration="", follow=""):
    values = dict.fromkeys(TARGETS_HEADER.split(","), "")
    values.update(
        TARGET_TYPE="1" if kind == "Cue" else "15",
        TARGET_TYPE_AS_TEXT=kind,
        TARGET_LIST_NUMBER=list_no,
        TARGET_ID=cue,
        PART_NUMBER=part,
        LABEL=label,
        CUE_NOTES=notes,
        SCENE_TEXT=scene,
        TIME_DATA=time,
        DOWN_TIME=down,
        DURATION=duration,
        FOLLOW=follow,
    )
    out = io.StringIO()
    csv.writer(out, lineterminator="\n").writerow(values.values())
    return out.getvalue()


EOS = (
    "START_LEVELS\n"
    "TARGET_TYPE,TARGET_TYPE_AS_TEXT,TARGET_LIST_NUMBER,TARGET_ID,CHANNEL,LEVEL\n"
    "1,Cue,1,1,101,50\n"
    "END_LEVELS\n"
    "START_TARGETS\n"
    + TARGETS_HEADER
    + "\n"
    + eos_row("Cue_List", "", "1", label="Main")
    + eos_row("Cue_List", "", "11", label="Rig Check")
    + eos_row("Cue", "1", "1", label="Preset", scene="Preshow", time="3.9", duration="3.9")
    + eos_row("Cue", "1", "2", label="House out, stage up", notes="Wait for HM clearance", duration="13")
    + eos_row("Cue", "1", "2", part="1", label="Part 1 of Q2", time="8", duration="8")
    + eos_row("Cue", "1", "2.5", label="Follow", time="5", down="1:00", duration="1:00", follow="F2")
    + eos_row("Cue", "11", "1", label="Rig check 1")
    + eos_row("Cue_List", "", "1", label="Main")  # Eos repeats list rows at the end
    + "END_TARGETS\n"
)


@pytest.fixture
def owner():
    return get_user_model().objects.create_user(username="alice", password="pw-for-tests")


@pytest.fixture
def production(owner):
    return Production.objects.create(owner=owner, name="Show A")


@pytest.fixture
def client(owner):
    c = APIClient()
    c.force_authenticate(owner)
    return c


def upload(client, production, body, **params):
    return client.post(f"/api/productions/{production.id}/cues/import/", {**body, **params}, format="multipart")


def eos_file():
    return SimpleUploadedFile("show.csv", EOS.encode(), content_type="text/csv")


@pytest.mark.django_db
def test_eos_export_needs_a_list_choice_when_several_have_cues(client, production):
    r = upload(client, production, {"file": eos_file()})
    assert r.status_code == 200
    assert r.data["format"] == "eos"
    assert r.data["lists"] == [
        {"number": "1", "label": "Main", "cues": 3},  # part row not counted
        {"number": "11", "label": "Rig Check", "cues": 1},
    ]
    assert r.data["summary"] is None
    assert upload(client, production, {"file": eos_file()}, dry_run="false").status_code == 400
    assert Cue.objects.count() == 0


@pytest.mark.django_db
def test_eos_import_of_one_list(client, production):
    dry = upload(client, production, {"file": eos_file()}, list="1")
    assert dry.data["summary"] == {"create": 3, "update": 0, "unchanged": 0, "delete": 0, "reject": 0}
    assert Cue.objects.count() == 0  # dry run by default

    applied = upload(client, production, {"file": eos_file()}, list="1", dry_run="false")
    assert applied.data["applied"] is True
    cues = list(production.cues.values_list("number", "label", "scene", "notes"))
    assert cues == [
        (Decimal("1"), "Preset", "Preshow", ""),
        (Decimal("2"), "House out, stage up", "", "Wait for HM clearance"),
        (Decimal("2.5"), "Follow", "", ""),
    ]
    times = list(production.cues.values_list("time", "down_time", "duration", "follow"))
    assert times == [
        (Decimal("3.9"), None, Decimal("3.9"), ""),
        (None, None, Decimal("13"), ""),  # the part row's time is not the cue's
        (Decimal("5"), Decimal("60"), Decimal("60"), "F2"),
    ]
    api = client.get(f"/api/productions/{production.id}/cues/").data[2]
    assert (api["time"], api["down_time"], api["duration"], api["follow"]) == ("5", "60", "60", "F2")


@pytest.mark.parametrize(
    "text, seconds",
    [("", None), ("0", "0"), ("3.9", "3.9"), ("1:00", "60"), ("2:00.5", "120.5"), ("1:02:03", "3723")],
)
def test_parse_seconds(text, seconds):
    assert csv_io.parse_seconds(text) == (None if seconds is None else Decimal(seconds))


@pytest.mark.parametrize("text", ["abc", "-1", "1:75", "1:2:3:4", "1000000", "nan"])
def test_parse_seconds_refuses(text):
    with pytest.raises(ValueError):
        csv_io.parse_seconds(text)


@pytest.mark.django_db
def test_new_times_without_a_duration_clear_the_eos_duration(client, production):
    Cue.objects.create(production=production, number=Decimal("1"), time=Decimal("5"), duration=Decimal("13"))
    Cue.objects.create(production=production, number=Decimal("2"), time=Decimal("5"), duration=Decimal("13"))
    Cue.objects.create(production=production, number=Decimal("3"), time=Decimal("5"), duration=Decimal("13"))
    # Q1 gets a new time and no duration; Q2 only a label, so its timing stands;
    # Q3 a new time with the same duration, which the file vouches for.
    text = "number,label,time,duration\n1,,8,\n2,Renamed,,\n3,,8,13\n"
    upload(client, production, {"text": text}, dry_run="false")
    assert list(production.cues.values_list("time", "duration")) == [
        (Decimal("8"), None),
        (Decimal("5"), Decimal("13")),
        (Decimal("8"), Decimal("13")),
    ]
    rejected = upload(client, production, {"text": "number,time,follow\n3,1:75,\n4,,X2\n"})
    assert [r["reason"][:6] for r in rejected.data["rows"]] == ["Time '", "Follow"]


@pytest.mark.django_db
def test_a_bare_follow_number_is_a_follow_and_zero_is_none(client, production):
    upload(client, production, {"text": "number,follow\n1,3\n2,0\n3,H1\n"}, dry_run="false")
    assert list(production.cues.values_list("follow", flat=True)) == ["F3", "", "H1"]


@pytest.mark.django_db
def test_merge_never_blanks_existing_fields_but_replace_does(client, production):
    Cue.objects.create(production=production, number=Decimal("1"), label="Typed here", page=4)
    Cue.objects.create(production=production, number=Decimal("9"), label="Not in file")
    text = "number,label,page\n1,,\n2,New,\n"

    merged = upload(client, production, {"text": text}, dry_run="false")
    assert merged.data["summary"] == {"create": 1, "update": 0, "unchanged": 1, "delete": 0, "reject": 0}
    assert production.cues.get(number=1).label == "Typed here"
    assert production.cues.filter(number=9).exists()

    replaced = upload(client, production, {"text": text}, mode="replace", dry_run="false")
    assert replaced.data["summary"] == {"create": 0, "update": 1, "unchanged": 1, "delete": 1, "reject": 0}
    assert list(production.cues.values_list("number", "label", "page")) == [
        (Decimal("1"), "", None),
        (Decimal("2"), "New", None),
    ]


@pytest.mark.django_db
def test_bad_rows_are_rejected_and_good_rows_still_import(client, production):
    text = "Number,Label,Page\n5,Good,3\nabc,Bad,\n0,Zero,\n6,Bad page,x\n5,Duplicate,\n7.12345,Too precise,\n"
    r = upload(client, production, {"text": text}, dry_run="false")
    reasons = [row["reason"] for row in r.data["rows"] if row["action"] == "reject"]
    assert len(reasons) == 5
    assert "not a number" in reasons[0]
    assert "greater than 0" in reasons[1]
    assert "whole number" in reasons[2]
    assert "more than once" in reasons[3]
    assert "too many digits" in reasons[4]
    assert list(production.cues.values_list("number", "label", "page")) == [(Decimal("5"), "Good", 3)]


@pytest.mark.django_db
def test_unreadable_files_are_refused(client, production):
    assert upload(client, production, {"text": "label,page\nA,1\n"}).status_code == 400  # no number column
    assert upload(client, production, {"text": "START_LEVELS\nEND_LEVELS\n"}).status_code == 400  # no cues section
    assert upload(client, production, {"text": "number\n1\n"}, mode="overwrite").status_code == 400


@pytest.mark.django_db
def test_export_round_trips_and_replace_keeps_run_logs(client, production):
    Cue.objects.create(production=production, number=Decimal("1"), label="Preset, warm", page=1, scene="Act 1")
    Cue.objects.create(production=production, number=Decimal("12.5"), label='Say "go"', notes="line 2")
    exported = client.get(f"/api/productions/{production.id}/cues/export/")
    assert exported["Content-Type"].startswith("text/csv")
    assert 'filename="show-a-cues.csv"' in exported["Content-Disposition"]
    body = exported.content.decode()

    again = upload(client, production, {"text": body})
    assert again.data["summary"] == {"create": 0, "update": 0, "unchanged": 2, "delete": 0, "reject": 0}

    run = Run.objects.create(production=production, label="Tech 1")
    client.post(f"/api/runs/{run.id}/go/", {}, format="json")
    upload(client, production, {"text": "number\n50\n"}, mode="replace", dry_run="false")
    assert list(production.cues.values_list("number", flat=True)) == [Decimal("50")]
    event = CueEvent.objects.get()
    assert (event.cue_id, event.cue_number, event.cue_label) == (None, Decimal("1"), "Preset, warm")

    log = client.get(f"/api/runs/{run.id}/export/").content.decode().splitlines()
    assert log[0] == "fired_at,seconds_from_start,action,cue_number,cue_label,note"
    assert log[1].endswith(',0.0,go,1,"Preset, warm",')


@pytest.mark.django_db
def test_import_and_export_are_owner_only(production):
    mallory = APIClient()
    mallory.force_authenticate(get_user_model().objects.create_user(username="mallory", password="x"))
    run = Run.objects.create(production=production, label="R")
    assert upload(mallory, production, {"text": "number\n1\n"}, dry_run="false").status_code == 404
    assert mallory.get(f"/api/productions/{production.id}/cues/export/").status_code == 404
    assert mallory.get(f"/api/runs/{run.id}/export/").status_code == 404
    assert upload(APIClient(), production, {"text": "number\n1\n"}).status_code == 401
    assert Cue.objects.count() == 0


@pytest.mark.django_db
def test_run_log_export_counts_seconds_from_the_first_event(client, production):
    Cue.objects.create(production=production, number=Decimal("1"))
    Cue.objects.create(production=production, number=Decimal("2"))
    run = Run.objects.create(production=production, label="Preview 1")
    for action in ("go", "go", "back"):
        client.post(f"/api/runs/{run.id}/{action}/", {}, format="json")
    # Set the times explicitly: three requests in one test land in the same
    # millisecond or so, which would let a wrong baseline pass.
    events = list(CueEvent.objects.order_by("id"))
    start = events[0].fired_at
    for event, offset in zip(events, (0, 7, 40)):
        CueEvent.objects.filter(pk=event.pk).update(fired_at=start + timedelta(seconds=offset))

    rows = list(csv.DictReader(io.StringIO(client.get(f"/api/runs/{run.id}/export/").content.decode())))
    assert [(r["seconds_from_start"], r["action"], r["cue_number"]) for r in rows] == [
        ("0.0", "go", "1"),
        ("7.0", "go", "2"),
        ("40.0", "back", "1"),
    ]
