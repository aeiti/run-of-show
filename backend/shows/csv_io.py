"""Cue list import and export.

Two input formats:

* **Simple CSV** with a header row; ``number`` is required, ``label``,
  ``page``, ``scene``, ``notes``, ``time``, ``down_time``, ``duration`` and
  ``follow`` are optional. This is also what export
  writes, so an export can be edited in a spreadsheet and imported back.
* **ETC Eos CSV export**, either cues only or a whole show file. Eos writes
  several sections (``START_LEVELS`` … ``END_LEVELS``, ``START_TARGETS`` …);
  cues live in the TARGETS section as rows whose ``TARGET_TYPE_AS_TEXT`` is
  ``Cue``. Cue numbers repeat across cue lists, so one list is imported at a
  time. Part rows (``PART_NUMBER`` set) are skipped: they belong to a cue
  that has its own row (its time is blank, and Eos's ``DURATION`` covers
  the parts). Checked against real Eos exports from two shows
  (one with 10 lists, point cues, parts, labels, scenes and notes).
"""

import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from .models import FOLLOW_VALIDATOR, Cue, format_number, normalize_follow

FIELDS = ["number", "label", "page", "scene", "notes", "time", "down_time", "duration", "follow"]
SECONDS = ["time", "down_time", "duration"]


class CsvImportError(Exception):
    """Raised for a file that can't be read at all (as opposed to bad rows)."""


def decode(raw):
    if isinstance(raw, str):
        return raw
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise CsvImportError("The file is not UTF-8 or Windows-1252 text.")


def is_eos(text):
    first = next((line for line in text.splitlines() if line.strip()), "")
    return first.strip().startswith("START_")


def eos_targets(text):
    """Cue lists and cue rows from the TARGETS section of an Eos export."""
    rows = list(csv.reader(io.StringIO(text)))
    try:
        start = next(i for i, r in enumerate(rows) if r[:1] == ["START_TARGETS"])
        end = next(i for i, r in enumerate(rows) if i > start and r[:1] == ["END_TARGETS"])
    except StopIteration:
        raise CsvImportError("This Eos export has no START_TARGETS section, so it contains no cues.")
    header = rows[start + 1]
    lists, cues = {}, []
    for row in rows[start + 2 : end]:
        record = dict(zip(header, row))
        kind = record.get("TARGET_TYPE_AS_TEXT")
        if kind == "Cue_List":
            lists[record["TARGET_ID"]] = record.get("LABEL", "")
        elif kind == "Cue" and not record.get("PART_NUMBER"):
            cues.append(
                {
                    "list": record.get("TARGET_LIST_NUMBER", ""),
                    "number": record.get("TARGET_ID", ""),
                    "label": record.get("LABEL", ""),
                    "page": "",
                    "scene": record.get("SCENE_TEXT", ""),
                    "notes": record.get("CUE_NOTES", ""),
                    "time": record.get("TIME_DATA", ""),
                    "down_time": record.get("DOWN_TIME", ""),
                    "duration": record.get("DURATION", ""),
                    "follow": record.get("FOLLOW", ""),
                }
            )
    counts = {}
    for cue in cues:
        counts[cue["list"]] = counts.get(cue["list"], 0) + 1
    summary = [
        {"number": number, "label": lists.get(number, ""), "cues": counts.get(number, 0)}
        for number in sorted(set(lists) | set(counts), key=_list_sort_key)
    ]
    return summary, cues


def _list_sort_key(number):
    try:
        return (0, Decimal(number))
    except InvalidOperation:
        return (1, number)


def simple_rows(text):
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise CsvImportError("The file is empty.")
    columns = {name.strip().lower(): name for name in reader.fieldnames if name}
    if "number" not in columns:
        raise CsvImportError("The first row must be a header with a 'number' column.")
    return [
        {field: (row.get(columns[field]) or "").strip() if field in columns else "" for field in FIELDS}
        for row in reader
    ]


def parse_seconds(text):
    """"3.9" -> 3.9, "1:00" -> 60, "1:02:03" -> 3723, "" -> None. Raises ValueError."""
    text = text.strip()
    if not text:
        return None
    parts = text.split(":")
    if len(parts) > 3:
        raise ValueError
    try:
        values = [Decimal(p) for p in parts]
    except InvalidOperation:
        raise ValueError
    if any(not v.is_finite() or v < 0 for v in values) or any(v >= 60 for v in values[1:]):
        raise ValueError
    seconds = Decimal(0)
    for v in values:
        seconds = seconds * 60 + v
    seconds = seconds.quantize(Decimal("0.01"))
    if seconds >= Decimal("1000000"):
        raise ValueError
    return seconds


def clean(raw):
    """(values, None) for a usable row, or (None, reason)."""
    text = raw["number"].strip()
    try:
        number = Decimal(text)
    except InvalidOperation:
        return None, f"Cue number {text!r} is not a number."
    if not number.is_finite() or number <= 0:
        return None, f"Cue number {text!r} must be greater than 0."
    if number.normalize().as_tuple().exponent < -4 or number >= Decimal("1000000"):
        return None, f"Cue number {text!r} has too many digits."
    page = raw.get("page", "").strip()
    if page and not page.isdigit():
        return None, f"Page {page!r} is not a whole number."
    times = {}
    for field in SECONDS:
        text = raw.get(field, "")
        try:
            times[field] = parse_seconds(text)
        except ValueError:
            return None, f"{field.replace('_', ' ').capitalize()} {text.strip()!r} is not a time in seconds or m:ss."
    follow = normalize_follow(raw.get("follow", ""))
    if follow:
        try:
            FOLLOW_VALIDATOR(follow)
        except ValidationError:
            return None, f"Follow {follow!r} should look like 2, F2 or H0.5."
    return {
        "number": number,
        "label": raw.get("label", "").strip()[:200],
        "page": int(page) if page else None,
        "scene": raw.get("scene", "").strip()[:200],
        "notes": raw.get("notes", "").strip(),
        **times,
        "follow": follow,
    }, None


def plan(production, text, mode="merge", eos_list=None):
    """Work out what an import would do, without changing anything."""
    if mode not in ("merge", "replace"):
        raise CsvImportError("Mode must be 'merge' or 'replace'.")
    text = decode(text)
    result = {"format": "simple", "lists": [], "list": None, "mode": mode}

    if is_eos(text):
        lists, rows = eos_targets(text)
        result.update(format="eos", lists=lists)
        with_cues = [entry["number"] for entry in lists if entry["cues"]]
        if eos_list is None and len(with_cues) == 1:
            eos_list = with_cues[0]
        if eos_list is None:
            # Ambiguous: report the lists so the user can pick one.
            result.update(rows=[], summary=None)
            return result
        result["list"] = str(eos_list)
        rows = [r for r in rows if r["list"] == str(eos_list)]
    else:
        rows = simple_rows(text)

    existing = {c.number: c for c in production.cues.all()}
    planned, seen = [], set()
    for line, raw in enumerate(rows, start=1):
        values, problem = clean(raw)
        if problem is None and values["number"] in seen:
            problem = f"Cue {format_number(values['number'])} appears more than once in the file."
        if problem:
            planned.append({"line": line, "action": "reject", "number": raw["number"], "reason": problem})
            continue
        seen.add(values["number"])
        current = existing.get(values["number"])
        if current is None:
            action, changes = "create", {f: values[f] for f in FIELDS[1:]}
        else:
            # Merge never blanks a field: Eos leaves most labels empty, and that
            # shouldn't wipe labels typed here. Replace takes the file as written.
            fields = [f for f in FIELDS[1:] if mode == "replace" or values[f] not in ("", None)]
            changes = {f: values[f] for f in fields if getattr(current, f) != values[f]}
            # As in the API: new times without a duration make the old Eos duration stale.
            if any(f in changes for f in ("time", "down_time")) and "duration" not in changes:
                if current.duration is not None and values["duration"] is None:
                    changes["duration"] = None
            action = "update" if changes else "unchanged"
        planned.append(
            {
                "line": line,
                "action": action,
                **values,
                "number": format_number(values["number"]),
                **{f: format_number(values[f]) for f in SECONDS},
                "changes": sorted(changes) if action == "update" else [],
                "_apply": changes,
            }
        )

    if mode == "replace":
        for number, cue in existing.items():
            if number not in seen:
                planned.append({"line": None, "action": "delete", "number": format_number(number), "label": cue.label})

    summary = {a: 0 for a in ("create", "update", "unchanged", "delete", "reject")}
    for row in planned:
        summary[row["action"]] += 1
    result.update(rows=planned, summary=summary)
    return result


def public(planned):
    """The plan as returned by the API, without the internal ``_apply`` field."""
    return {**planned, "rows": [{k: v for k, v in row.items() if k != "_apply"} for row in planned["rows"]]}


@transaction.atomic
def apply(production, planned):
    """Carry out a plan from ``plan()``. Rejected rows are skipped."""
    for row in planned["rows"]:
        action = row["action"]
        number = Decimal(row["number"]) if action != "reject" else None
        if action == "create":
            Cue.objects.create(production=production, number=number, **row["_apply"])
        elif action == "update":
            Cue.objects.filter(production=production, number=number).update(**row["_apply"])
        elif action == "delete":
            # Run logs keep their own copy of each cue's number and label.
            Cue.objects.filter(production=production, number=number).delete()


def export_cues(production):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(FIELDS)
    for cue in production.cues.all():
        times = [format_number(getattr(cue, f)) or "" for f in SECONDS]
        writer.writerow([format_number(cue.number), cue.label, cue.page or "", cue.scene, cue.notes, *times, cue.follow])
    return out.getvalue()


def export_run(run):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["fired_at", "seconds_from_start", "action", "cue_number", "cue_label", "note"])
    start = None
    for event in run.events.all():
        start = start or event.fired_at
        writer.writerow(
            [
                event.fired_at.isoformat(),
                f"{(event.fired_at - start).total_seconds():.1f}",
                event.action,
                format_number(event.cue_number) or "",
                event.cue_label,
                event.note,
            ]
        )
    return out.getvalue()
