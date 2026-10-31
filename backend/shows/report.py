"""The show report for one run: its times, holds, scene lengths and notes.

Everything is worked out here, once, from the run's own records: the API
returns ``build(run)`` as JSON, the frontend prints it, and ``as_text`` and
``as_html`` are the email.

Times are measured up to the run's end. A run still going is measured up to
``as_of`` (when the report was made) and marked ``in_progress``, and so is a
hold never resumed: it lasts until the run ended, or until now.

Scenes are the "act lengths". A cue's scene is the scene text on it or on the
nearest cue before it, as on the board. A scene starts when a GO, GOTO or BACK
first makes one of its cues active and lasts until another scene's cue is
made active, or the run ends. Going back into a scene starts it again, so a
stopped and restarted rehearsal shows each pass. Scenes are found from the
cue number recorded on each event against the current cue list, so a cue
deleted since the run still counts towards the scene it was in.

Performance notes are listed in the order they happened (``at``), each with
where the show was: the run clock (playing time since the start, held time
left out, as in the scene lengths), the scene, and the hold it was written
in, if any. These are worked out from the note's time, so correcting the
run's start corrects them. A note added later with no time comes last.
"""

from bisect import bisect_right

from django.utils import timezone
from django.utils.html import format_html, format_html_join

from accounts.models import shown_name

from .models import CueEvent, format_number

# The actions that make a cue active. A reset clears it, but the show is
# still in the same scene until another cue goes.
MOVES = {CueEvent.Action.GO, CueEvent.Action.GOTO, CueEvent.Action.BACK}


def _seconds(start, end):
    return round((end - start).total_seconds(), 3)


def _overlap(start, end, spans):
    """Seconds of ``spans`` (pairs of times) that fall between ``start`` and ``end``."""
    total = 0.0
    for a, b in spans:
        lo, hi = max(start, a), min(end, b)
        if hi > lo:
            total += (hi - lo).total_seconds()
    return round(total, 3)


def holds(events, until):
    """Each hold with its reason and length; one never resumed lasts until ``until``."""
    found = []
    for event in events:
        if event.action == CueEvent.Action.HOLD:
            found.append({"event": event, "resumed_at": None})
        elif event.action == CueEvent.Action.RESUME and found and found[-1]["resumed_at"] is None:
            found[-1]["resumed_at"] = event.fired_at
    return [
        {
            "reason": h["event"].note,
            "cue_number": format_number(h["event"].cue_number),
            "cue_label": h["event"].cue_label,
            "started_at": h["event"].fired_at,
            "resumed_at": h["resumed_at"],
            "seconds": _seconds(h["event"].fired_at, h["resumed_at"] or until),
        }
        for h in found
    ]


def _scene_lookup(cues):
    """A function from a cue number to its scene ("" before the first scene)."""
    numbers, names, current = [], [], ""
    for cue in cues:
        if cue.scene:
            current = cue.scene
        numbers.append(cue.number)
        names.append(current)

    def scene_of(number):
        i = bisect_right(numbers, number)
        return names[i - 1] if i else ""

    return scene_of


def scenes(events, scene_of, until, hold_spans):
    """Each pass through a scene in run order, with its length and the time held within it."""
    passes = []
    for event in events:
        if event.action not in MOVES or event.cue_number is None:
            continue
        name = scene_of(event.cue_number)
        if passes and passes[-1]["name"] == name:
            continue
        passes.append({"name": name, "started_at": event.fired_at, "first_cue": format_number(event.cue_number)})
    for current, following in zip(passes, passes[1:] + [None]):
        end = following["started_at"] if following else until
        current["ended_at"] = following["started_at"] if following else None
        current["seconds"] = _seconds(current["started_at"], end)
        current["held_seconds"] = _overlap(current["started_at"], end, hold_spans)
    return passes


def _playing_seconds(start, moment, spans):
    """The run clock at ``moment``: time since the start, less the time held. None before the start."""
    if start is None or moment < start:
        return None
    return round(_seconds(start, moment) - _overlap(start, moment, spans), 3)


def performance_notes(notes, events, scene_of, start, found_holds, until):
    """Each note in the order it happened, with the run clock, scene and hold at its moment."""
    spans = [(h["started_at"], h["resumed_at"] or until) for h in found_holds]
    moves = [e for e in events if e.action in MOVES and e.cue_number is not None]
    items = []
    for note in sorted(notes, key=lambda n: (n.at is None, n.at or n.created_at, n.id)):
        moment = note.at
        hold = None
        if moment is not None:
            hold = next((h for h in found_holds if h["started_at"] <= moment < (h["resumed_at"] or until)), None)
        # The note's own cue, else the last cue made active before it.
        number = note.cue_number
        if number is None and moment is not None:
            number = next((e.cue_number for e in reversed(moves) if e.fired_at <= moment), None)
        items.append({
            "id": note.id,
            "cue_number": format_number(note.cue_number),
            "cue_label": note.cue_label,
            "scene": scene_of(number) if number is not None else "",
            "text": note.text,
            "author": shown_name(note.author),
            "at": moment,
            "clock_seconds": _playing_seconds(start, moment, spans) if moment else None,
            "in_hold": hold is not None,
            "hold_reason": hold["reason"] if hold else "",
            "added_later": note.added_later,
            "follow_up": note.follow_up,
            "follow_up_by": shown_name(note.follow_up_by),
            "follow_up_at": note.follow_up_at,
            "created_at": note.created_at,
            "updated_at": note.updated_at,
        })
    return items


def build(run, now=None):
    """The report as plain data (datetimes and numbers), ready for a serializer or JSON."""
    production = run.production
    events = sorted(run.events.all(), key=lambda e: (e.fired_at, e.id))
    as_of = now or timezone.now()
    until = run.ended_at or as_of

    found_holds = holds(events, until)
    spans = [(h["started_at"], h["resumed_at"] or until) for h in found_holds]
    start = run.started_at
    scene_of = _scene_lookup(list(production.cues.all()))
    return {
        "as_of": as_of,
        "in_progress": run.ended_at is None,
        "production": {
            "id": production.id,
            "name": production.name,
            "company": production.company,
            "venue": production.venue,
            "opening_date": production.opening_date,
            "closing_date": production.closing_date,
        },
        "run": {
            "id": run.id,
            "label": run.label,
            "kind": run.kind,
            "scheduled_start": run.scheduled_start,
            "started_at": start,
            "ended_at": run.ended_at,
        },
        "timing": {
            # Positive when the run went up late.
            "late_seconds": _seconds(run.scheduled_start, start) if start and run.scheduled_start else None,
            "running_seconds": _seconds(start, until) if start else None,
            # Held time between the start and the end, so "running minus held" is the playing time.
            "held_in_run_seconds": _overlap(start, until, spans) if start else None,
            "cues_fired": sum(1 for e in events if e.action in (CueEvent.Action.GO, CueEvent.Action.GOTO)),
        },
        "holds": {
            "count": len(found_holds),
            "total_seconds": round(sum(h["seconds"] for h in found_holds), 3),
            "items": found_holds,
        },
        "scenes": scenes(events, scene_of, until, spans),
        "performance_notes": performance_notes(
            run.cue_notes.select_related("author__profile", "follow_up_by__profile"),
            events, scene_of, start, found_holds, until,
        ),
        "notes": run.notes,
    }


# Text and HTML for email. Times are shown in the server's time zone
# (settings.TIME_ZONE), which is the only one the server knows.


def clock(seconds):
    """75.4 -> "1:15", 3723 -> "1:02:03", as on the board."""
    if seconds is None:
        return "–"
    s = max(0, int(seconds))
    h, m, ss = s // 3600, s % 3600 // 60, s % 60
    return f"{h}:{m:02}:{ss:02}" if h else f"{m}:{ss:02}"


def _when(value):
    return timezone.localtime(value).strftime("%a %d %b %Y, %H:%M:%S") if value else "–"


def _late(seconds):
    if seconds is None:
        return ""
    if abs(seconds) < 60:
        return "on time"
    return f"{clock(abs(seconds))} {'late' if seconds > 0 else 'early'}"


def _dates(production):
    opening, closing = production["opening_date"], production["closing_date"]
    if opening and closing:
        return f"{opening:%d %b %Y} – {closing:%d %b %Y}"
    if opening:
        return f"Opens {opening:%d %b %Y}"
    if closing:
        return f"Closes {closing:%d %b %Y}"
    return ""


def subject(report):
    return f"Show report: {report['production']['name']}, {report['run']['label']}"


def _summary_rows(report):
    run, timing, held = report["run"], report["timing"], report["holds"]
    started, late = _when(run["started_at"]), _late(timing["late_seconds"])
    running = clock(timing["running_seconds"])
    if report["in_progress"] and timing["running_seconds"] is not None:
        running += " so far"
    return [
        ("Scheduled", _when(run["scheduled_start"])),
        ("Started", f"{started} ({late})" if late else started),
        ("Ended", _when(run["ended_at"]) if run["ended_at"] else "Still running"),
        ("Running time", running),
        ("Holds", f"{held['count']}, {clock(held['total_seconds'])} in all"),
    ]


def _scene_name(scene):
    return scene["name"] or "Before the first scene"


def _cue(number, label):
    return " ".join(filter(None, [f"Q{number}" if number else "", label]))


def _note_where(note):
    return " · ".join(filter(None, [_cue(note["cue_number"], note["cue_label"]), note["scene"]]))


def _note_stamp(note):
    """The note's time of day and run clock, "19:42:10 · 0:08:10", or why it has none."""
    if note["at"] is None:
        return "Added later"
    stamp = f"{timezone.localtime(note['at']):%H:%M:%S}"
    if note["clock_seconds"] is not None:
        stamp += f" · {clock(note['clock_seconds'])}"
    return stamp


def _note_flags(note):
    flags = []
    if note["in_hold"]:
        flags.append(f"in hold: {note['hold_reason']}" if note["hold_reason"] else "in hold")
    if note["added_later"] and note["at"] is not None:
        flags.append("added later")
    return ", ".join(flags)


def as_text(report):
    production, run = report["production"], report["run"]
    lines = [
        subject(report),
        "",
        " · ".join(filter(None, [production["company"], production["venue"], _dates(production)])),
        f"{run['label']} ({run['kind']})",
        "",
    ]
    lines += [f"{label}: {value}" for label, value in _summary_rows(report)]

    if report["scenes"]:
        lines += ["", "SCENES"]
        for scene in report["scenes"]:
            held = f" (held {clock(scene['held_seconds'])})" if scene["held_seconds"] else ""
            lines.append(f"  {_scene_name(scene)}: {clock(scene['seconds'])}{held}")

    if report["holds"]["items"]:
        lines += ["", "HOLDS"]
        for hold in report["holds"]["items"]:
            at = _cue(hold["cue_number"], "")
            resumed = "" if hold["resumed_at"] else ", not resumed"
            lines.append(
                f"  {timezone.localtime(hold['started_at']):%H:%M:%S}  {clock(hold['seconds'])}{resumed}  "
                f"{hold['reason']}{f' (at {at})' if at else ''}"
            )

    if report["performance_notes"]:
        lines += ["", "PERFORMANCE NOTES"]
        for note in report["performance_notes"]:
            where, flags = _note_where(note), _note_flags(note)
            by = f" ({note['author']})" if note["author"] else ""
            lines.append(
                f"  {_note_stamp(note)}{f'  {where}' if where else ''}{f' [{flags}]' if flags else ''}"
            )
            lines.append(f"    {note['text']}{by}")
            if note["follow_up"]:
                follow_by = f" ({note['follow_up_by']})" if note["follow_up_by"] else ""
                lines.append(f"    Follow-up: {note['follow_up']}{follow_by}")

    if report["notes"]:
        lines += ["", "NOTES", report["notes"]]

    lines += ["", f"Report made {_when(report['as_of'])}."]
    return "\n".join(lines) + "\n"


def as_html(report):
    """The same report as simple HTML. Every value is escaped by format_html."""
    production, run = report["production"], report["run"]
    parts = [
        format_html("<h1>{}</h1>", subject(report)),
        format_html(
            "<p>{}<br>{} ({})</p>",
            " · ".join(filter(None, [production["company"], production["venue"], _dates(production)])),
            run["label"],
            run["kind"],
        ),
        format_html(
            "<table>{}</table>",
            format_html_join("", "<tr><th align='left'>{}</th><td>{}</td></tr>", _summary_rows(report)),
        ),
    ]
    if report["scenes"]:
        parts.append(format_html("<h2>Scenes</h2><table>{}</table>", format_html_join(
            "",
            "<tr><td>{}</td><td>{}</td><td>{}</td></tr>",
            (
                (_scene_name(s), clock(s["seconds"]), f"held {clock(s['held_seconds'])}" if s["held_seconds"] else "")
                for s in report["scenes"]
            ),
        )))
    if report["holds"]["items"]:
        parts.append(format_html("<h2>Holds</h2><table>{}</table>", format_html_join(
            "",
            "<tr><td>{}</td><td>{}</td><td>{}</td><td>{}</td></tr>",
            (
                (
                    f"{timezone.localtime(h['started_at']):%H:%M:%S}",
                    clock(h["seconds"]) + ("" if h["resumed_at"] else ", not resumed"),
                    h["reason"],
                    _cue(h["cue_number"], ""),
                )
                for h in report["holds"]["items"]
            ),
        )))
    if report["performance_notes"]:
        items = []
        for n in report["performance_notes"]:
            flags = _note_flags(n)
            follow_up = format_html(
                "<br><i>Follow-up:</i> <span style='white-space: pre-wrap'>{}</span> <i>{}</i>",
                n["follow_up"],
                n["follow_up_by"],
            ) if n["follow_up"] else ""
            items.append(format_html(
                "<li><small>{}</small> <b>{}</b>{}<br><span style='white-space: pre-wrap'>{}</span> <i>{}</i>{}</li>",
                _note_stamp(n),
                _note_where(n),
                f" [{flags}]" if flags else "",
                n["text"],
                n["author"],
                follow_up,
            ))
        parts.append(format_html("<h2>Performance notes</h2><ul>{}</ul>", format_html_join("", "{}", ((i,) for i in items))))
    if report["notes"]:
        parts.append(format_html("<h2>Notes</h2><p style='white-space: pre-wrap'>{}</p>", report["notes"]))
    parts.append(format_html("<p><small>Report made {}.</small></p>", _when(report["as_of"])))
    return "".join(parts)
