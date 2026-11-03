import { Fragment, useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { can } from '../access'
import { findByNumber } from '../board/state'
import { groupFiles, formatSize } from '../board/files'
import { formatDateRange, fromLocalInput, keepSeconds, toLocalInput } from '../dates'
import {
  actClock,
  actName,
  bySection,
  daySections,
  GENERAL,
  pickableSections,
  cueText,
  lateness,
  length,
  noteMoment,
  noteWhere,
  parseAddresses,
  sceneName,
  timeline,
} from './reportText'

const when = (iso) =>
  iso
    ? new Date(iso).toLocaleString([], {
        weekday: 'short',
        day: 'numeric',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      })
    : '–'
const clockTime = (iso) =>
  new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })

/**
 * Send the report to a few addresses; operators and up. It goes as the
 * distributed report, with each note's stamps only if asked, and any of the
 * production's files attached (the latest version of each).
 */
function EmailForm({ runId, files, scope }) {
  const [text, setText] = useState('')
  const [stamps, setStamps] = useState(false)
  const [attached, setAttached] = useState([])
  const latest = groupFiles(files).map((g) => g.versions[0])
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const [error, setError] = useState('')

  async function send(e) {
    e.preventDefault()
    const to = parseAddresses(text)
    if (!to.length) return
    setBusy(true)
    setError('')
    setResult(null)
    try {
      setResult(await api.emailReport(runId, to, stamps, attached, scope))
      setText('')
    } catch (err) {
      setError(err.status === 429 ? 'Too many reports sent. Try again later.' : err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="report-email" onSubmit={send}>
      <input
        aria-label="Email addresses"
        placeholder="Email to: sm@example.com, lx@example.com"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <label className="report-email-stamps">
        <input type="checkbox" checked={stamps} onChange={(e) => setStamps(e.target.checked)} />
        With note times and cues
      </label>
      <button type="submit" disabled={busy || !parseAddresses(text).length}>
        {busy ? 'Sending…' : 'Email'}
      </button>
      {latest.length > 0 && (
        <details className="report-attach">
          <summary>Attach files{attached.length ? ` (${attached.length})` : ''}</summary>
          {latest.map((f) => (
            <label key={f.id}>
              <input
                type="checkbox"
                checked={attached.includes(f.id)}
                onChange={(e) =>
                  setAttached((prev) => (e.target.checked ? [...prev, f.id] : prev.filter((id) => id !== f.id)))
                }
              />
              {f.name} <span className="muted">({formatSize(f.size)})</span>
            </label>
          ))}
        </details>
      )}
      {result && <p className="ok">Sent to {result.to.join(', ')}.</p>}
      {error && <p className="error">{error}</p>}
    </form>
  )
}

/**
 * One performance note: when and where it happened, the text written live,
 * and the follow-up written afterwards. Operators write the follow-up; the
 * live text stays as it was written.
 */
function PerformanceNote({ note, sections, canEdit, onChanged }) {
  const [draft, setDraft] = useState(null) // null: not writing the follow-up
  const [error, setError] = useState('')
  const where = noteWhere(note)

  async function change(data) {
    setError('')
    try {
      await api.updateCueNote(note.id, data)
      onChanged()
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  async function save(e) {
    e.preventDefault()
    if (await change({ follow_up: draft.trim() })) setDraft(null)
  }

  return (
    <li>
      <div className="note-stamp">
        {note.at ? <time dateTime={note.at}>{clockTime(note.at)}</time> : <span>Time not set</span>}
        {note.clock_seconds !== null && (
          <span title="Run clock: time since the start, holds left out"> · {length(note.clock_seconds)}</span>
        )}
        {where && <span className="note-where"> · {where}</span>}
        {note.in_hold && <span className="note-flag">{note.hold_reason ? `Held: ${note.hold_reason}` : 'Held'}</span>}
        {note.added_later && <span className="note-flag">Added later</span>}
      </div>
      <p className="pre">
        {note.text}
        {note.author && <span className="muted"> ({note.author})</span>}
      </p>
      {canEdit && (
        <div className="row note-sorting no-print">
          <select
            aria-label="Section"
            value={note.section === GENERAL ? '' : note.section}
            onChange={(e) => change({ section: e.target.value })}
          >
            <option value="">{GENERAL}</option>
            {/* A section since taken off the production's list stays pickable for this note. */}
            {[
              ...pickableSections(sections),
              ...(note.section && note.section !== GENERAL && !sections.includes(note.section) ? [note.section] : []),
            ].map((name) => (
              <option key={name}>{name}</option>
            ))}
          </select>
          <label title="Print the cue and scene with this note in the distributed report">
            <input type="checkbox" checked={note.show_cue} onChange={(e) => change({ show_cue: e.target.checked })} />
            Show cue in report
          </label>
        </div>
      )}
      {!canEdit && <div className="note-stamp">{note.section || GENERAL}</div>}
      {draft === null ? (
        <>
          {note.follow_up && (
            <p className="note-follow-up pre">
              <em>Follow-up:</em> {note.follow_up}
              {note.follow_up_by && <span className="muted"> ({note.follow_up_by})</span>}
            </p>
          )}
          {canEdit && (
            <button className="ghost small no-print" onClick={() => setDraft(note.follow_up)}>
              {note.follow_up ? 'Edit follow-up' : 'Add follow-up'}
            </button>
          )}
        </>
      ) : (
        <form className="report-note-form no-print" onSubmit={save}>
          <textarea
            autoFocus
            rows={2}
            maxLength={4000}
            aria-label="Follow-up"
            placeholder="What happened, what's being done about it"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setDraft(null)}
          />
          <div className="row">
            <button type="submit" className="small" disabled={draft.trim() === note.follow_up}>
              Save follow-up
            </button>
            <button type="button" className="ghost small" onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
      {error && <p className="error no-print">{error}</p>}
    </li>
  )
}

/** A note not caught live, with a cue and a time of day if the SM knows them. */
function AddLaterNote({ runId, cues, sections, baseIso, onAdded }) {
  const [text, setText] = useState('')
  const [section, setSection] = useState('')
  const [number, setNumber] = useState('')
  const [time, setTime] = useState('')
  const [error, setError] = useState('')
  const cue = findByNumber(cues, number)
  const cueOk = !number.trim() || cue

  async function add(e) {
    e.preventDefault()
    if (!cueOk || !text.trim()) return
    setError('')
    try {
      await api.addCueNote(runId, {
        text: text.trim(),
        cue: cue?.id ?? null,
        at: noteMoment(time, baseIso),
        added_later: true,
        section,
      })
      setText('')
      setNumber('')
      setTime('')
      onAdded()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="report-note-form no-print" onSubmit={add}>
      <textarea
        rows={2}
        maxLength={2000}
        aria-label="Note added later"
        placeholder="A note not caught during the show"
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <div className="row">
        <input
          className="narrow"
          aria-label="Cue (optional)"
          placeholder="Q#"
          inputMode="decimal"
          value={number}
          onChange={(e) => setNumber(e.target.value)}
        />
        <input type="time" aria-label="Time (optional)" value={time} onChange={(e) => setTime(e.target.value)} />
        <select aria-label="Section" value={section} onChange={(e) => setSection(e.target.value)}>
          <option value="">{GENERAL}</option>
          {pickableSections(sections).map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
        <button type="submit" className="small" disabled={!cueOk || !text.trim()}>
          Add note
        </button>
        {!cueOk && <span className="error">No Q{number} in the list.</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

/** One act's times in the editor, or a new act's when ``act`` is null. */
function ActEditRow({ act, onSave, onDelete }) {
  const [up, setUp] = useState(toLocalInput(act?.up_at))
  const [down, setDown] = useState(toLocalInput(act?.down_at))

  async function save(e) {
    e.preventDefault()
    const body = {
      up_at: keepSeconds(act?.up_at, fromLocalInput(up)),
      down_at: keepSeconds(act?.down_at, fromLocalInput(down)),
    }
    if ((await onSave(body)) && !act) {
      setUp('')
      setDown('')
    }
  }

  return (
    <form className="row act-edit report-note-form" onSubmit={save}>
      <span className="act-edit-name">{act ? actName(act.number) : 'New act'}</span>
      <label>
        Up
        <input type="datetime-local" required value={up} onChange={(e) => setUp(e.target.value)} />
      </label>
      <label>
        Down
        <input type="datetime-local" value={down} onChange={(e) => setDown(e.target.value)} />
      </label>
      <button type="submit" className="small" disabled={!up}>
        {act ? 'Save' : 'Add act'}
      </button>
      {act && (
        <button type="button" className="ghost small" onClick={onDelete}>
          Delete
        </button>
      )}
    </form>
  )
}

/**
 * The times block a performance report opens with: each act's time up, time
 * down and length (holds included, held time beside it), the intermission
 * between acts, and the totals. Operators correct the times or add acts.
 * A run with no acts leaves it out of the printed report.
 */
/** [label, value] rows for an acts block, as the sample reports lay it out. */
function actRows(block) {
  const rows = []
  for (const a of block.items) {
    const name = actName(a.number)
    if (a.intermission_before_seconds !== null) rows.push(['Intermission', length(a.intermission_before_seconds)])
    const held = a.held_seconds ? ` (held ${length(a.held_seconds)})` : ''
    rows.push(
      [`${name} up`, actClock(a.up_at)],
      [`${name} down`, actClock(a.down_at)],
      [`${name} total`, `${length(a.seconds)}${a.down_at ? '' : ' so far'}${held}`],
    )
  }
  if (block.items.length) {
    rows.push(['Total (without intermission)', length(block.total_seconds)], ['Show total', length(block.show_seconds)])
  }
  return rows
}

function ActTimes({ runId, block, canEdit, onChanged }) {
  const [editing, setEditing] = useState(false)
  const [error, setError] = useState('')

  async function call(fn) {
    setError('')
    try {
      await fn()
      onChanged()
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  const rows = actRows(block)

  return (
    <section className={block.items.length ? '' : 'no-print'}>
      <div className="row-between">
        <h2>Acts</h2>
        {canEdit && (
          <button className="ghost small no-print report-edit-toggle" onClick={() => setEditing(!editing)}>
            {editing ? 'Done' : 'Edit times'}
          </button>
        )}
      </div>
      {editing ? (
        <>
          {block.items.map((a) => (
            <ActEditRow
              key={`${a.id}-${a.up_at}-${a.down_at}`}
              act={a}
              onSave={(data) => call(() => api.updateAct(a.id, data))}
              onDelete={() => call(() => api.deleteAct(a.id))}
            />
          ))}
          <ActEditRow key={`new-${block.items.length}`} onSave={(data) => call(() => api.addAct(runId, data))} />
        </>
      ) : rows.length === 0 ? (
        <p className="muted">
          No acts marked.{canEdit && ' Bring acts up and down on the board, flag cues in the editor, or add them here.'}
        </p>
      ) : (
        <dl className="report-summary">
          {rows.map(([label, value]) => (
            <Fragment key={label}>
              <dt>{label}</dt>
              <dd>{value}</dd>
            </Fragment>
          ))}
        </dl>
      )}
      {error && <p className="error no-print">{error}</p>}
    </section>
  )
}

/**
 * Who and what this performance is: the number (counted, or set by hand),
 * a label for a special performance, and the stage managers calling it.
 * Operators edit them here.
 */
function HeaderEdit({ runId, run, header, stageManagers, onDone }) {
  const [draft, setDraft] = useState({
    performance_number: run.performance_number ?? '',
    special_label: run.special_label,
    stage_managers: run.stage_managers,
  })
  const [error, setError] = useState('')

  async function save(e) {
    e.preventDefault()
    try {
      await api.updateRun(runId, { ...draft, performance_number: draft.performance_number === '' ? null : Number(draft.performance_number) })
      onDone(true)
    } catch (err) {
      setError(err.message)
    }
  }

  const field = (key) => ({ value: draft[key], onChange: (e) => setDraft({ ...draft, [key]: e.target.value }) })
  return (
    <form className="report-note-form report-header-form no-print" onSubmit={save}>
      {header.number !== null && (
        <label>
          Number
          <input type="number" min={1} placeholder={`${header.number} (counted)`} {...field('performance_number')} />
        </label>
      )}
      <label>
        Special performance
        <input maxLength={200} placeholder="Opening Night" {...field('special_label')} />
      </label>
      <label>
        Stage managers
        <input
          maxLength={500}
          placeholder={stageManagers.inherited ? `${stageManagers.names} (as last time)` : 'Names, comma separated'}
          {...field('stage_managers')}
        />
      </label>
      <div className="row">
        <button type="submit" className="small">
          Save
        </button>
        <button type="button" className="ghost small" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

/**
 * The next call, worked out from the next scheduled run and the production's
 * call template unless the SM has written their own, which they can edit or
 * put back to the worked-out one.
 */
function NextCall({ runId, call, canEdit, onChanged }) {
  const [draft, setDraft] = useState(null) // null: not editing
  const [error, setError] = useState('')

  async function save(value) {
    setError('')
    try {
      await api.updateRun(runId, { next_call: value })
      setDraft(null)
      onChanged()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <section className={call.text ? '' : 'no-print'}>
      <div className="row-between">
        <h2>Next call</h2>
        {canEdit && draft === null && (
          <span className="row no-print">
            {call.edited && call.generated && (
              <button className="ghost small report-edit-toggle" onClick={() => save('')}>
                Use the worked-out call
              </button>
            )}
            <button className="ghost small report-edit-toggle" onClick={() => setDraft(call.text)}>
              Edit
            </button>
          </span>
        )}
      </div>
      {draft !== null ? (
        <form
          className="report-note-form no-print"
          onSubmit={(e) => {
            e.preventDefault()
            save(draft.trim())
          }}
        >
          <textarea rows={6} aria-label="Next call" value={draft} onChange={(e) => setDraft(e.target.value)} />
          <div className="row">
            <button type="submit" className="small">
              Save
            </button>
            <button type="button" className="ghost small" onClick={() => setDraft(null)}>
              Cancel
            </button>
          </div>
        </form>
      ) : call.text ? (
        <p className="pre">{call.text}</p>
      ) : (
        <p className="muted">No run is scheduled after this one. Add one with a scheduled start, or write the call here.</p>
      )}
      {error && <p className="error no-print">{error}</p>}
    </section>
  )
}

const VIEW_KEY = 'ros-report-view'
function storedView() {
  try {
    return localStorage.getItem(VIEW_KEY) === 'distributed' ? 'distributed' : 'working'
  } catch {
    return 'working'
  }
}

/**
 * The SM's working view: every note with its time, run clock and cue,
 * between the scene changes and holds, for writing the report up.
 */
function WorkingNotes({ report, canEdit, onChanged }) {
  const items = timeline(report.scenes, report.holds.items, report.performance_notes)
  if (!report.performance_notes.length) return <p className="muted">No performance notes.</p>
  return (
    <ol className="report-notes">
      {items.map((item) =>
        item.kind === 'note' ? (
          <PerformanceNote
            key={item.key}
            note={item.note}
            sections={report.sections}
            canEdit={canEdit}
            onChanged={onChanged}
          />
        ) : item.kind === 'scene' ? (
          <li key={item.key} className="timeline-mark">
            <time dateTime={item.at}>{clockTime(item.at)}</time> · {sceneName(item.scene)}
          </li>
        ) : (
          <li key={item.key} className="timeline-mark">
            <time dateTime={item.at}>{clockTime(item.at)}</time> · Hold {length(item.hold.seconds)}
            {item.hold.reason && `: ${item.hold.reason}`}
          </li>
        ),
      )}
    </ol>
  )
}

/**
 * The report as it goes out: notes as prose under the production's sections,
 * without stamps. A note's cue and scene show only where the SM asked.
 */
function DistributedNotes({ report }) {
  return bySection(report.sections, report.performance_notes).map(([section, notes]) => (
    <div key={section} className="report-section">
      <h3>{section}</h3>
      {notes.length === 0 ? (
        <p className="muted">Nothing to report.</p>
      ) : (
        <ul>
          {notes.map((n) => (
            <li key={n.id}>
              <span className="pre">{n.text}</span>
              {n.show_cue && noteWhere(n) && <span className="muted"> ({noteWhere(n)})</span>}
              {n.follow_up && <p className="note-follow-up pre">{n.follow_up}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  ))
}

const dayTime = (iso) => (iso ? new Date(iso).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }) : '–')

/**
 * One show's summary and act times, as [label, value] rows for the day's
 * side-by-side table. Times of day only: the header gives the date.
 */
function showTimes(show) {
  const { run, timing, holds } = show
  const late = lateness(timing.late_seconds)
  return [
    ['Scheduled', dayTime(run.scheduled_start)],
    ['Started', run.started_at ? `${dayTime(run.started_at)}${late ? ` (${late})` : ''}` : 'Not started'],
    ['Ended', run.ended_at ? dayTime(run.ended_at) : 'Still running'],
    ['Running time', length(timing.running_seconds)],
    ['Holds', `${holds.count}, ${length(holds.total_seconds)} in all`],
    ...actRows(show.acts),
  ]
}

/**
 * The combined report for a day's shows: one header, the shows' times side by
 * side, each section's notes split by show, the last show's next call and one
 * sign-off. Read-only: each show's own report is where its notes, acts and
 * next call are edited.
 */
function DayReport({ runId, onLoaded }) {
  const [day, setDay] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    api.dayReport(runId).then(
      (d) => {
        if (cancelled) return
        setDay(d)
        onLoaded(d)
      },
      (e) => !cancelled && setError(e.message),
    )
    return () => {
      cancelled = true
    }
    // onLoaded only names the page; the day is fetched once per run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId])

  if (error) return <p className="error">{error}</p>
  if (!day) return <p className="muted">Loading the day's report…</p>

  const { production, shows } = day
  const columns = shows.map((show) => new Map(showTimes(show)))
  const labels = [...new Set(shows.flatMap((show) => showTimes(show).map(([label]) => label)))]
  return (
    <>
      <header>
        <p className="report-kicker">Show report</p>
        <h1>{production.name}</h1>
        <p className="report-headline">
          <strong>
            {day.title} · {day.date}
          </strong>
        </p>
        {day.special_labels.map((label) => (
          <p key={label} className="report-special">
            {label}
          </p>
        ))}
        <p>
          {[production.company, production.venue, formatDateRange(production.opening_date, production.closing_date)]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {day.in_progress && <p className="report-warning">Still running: times are up to {when(day.as_of)}.</p>}
      </header>

      <section>
        <h2>Times</h2>
        <table className="report-table day-times">
          <thead>
            <tr>
              <th />
              {shows.map((show) => (
                <th key={show.run.id}>{show.header.title}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {labels.map((label) => (
              <tr key={label}>
                <th scope="row">{label}</th>
                {columns.map((column, i) => (
                  <td key={shows[i].run.id}>{column.get(label) ?? ''}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section>
        <h2>Performance notes</h2>
        {daySections(day.sections, shows).map(([section, perShow]) => (
          <div key={section} className="report-section">
            <h3>{section}</h3>
            {perShow.every((notes) => notes.length === 0) ? (
              <p className="muted">Nothing to report.</p>
            ) : (
              shows.map((show, i) => (
                <div key={show.run.id} className="day-show-notes">
                  <p className="day-show-name">{show.header.title}:</p>
                  {perShow[i].length === 0 ? (
                    <p className="muted">None.</p>
                  ) : (
                    <ul>
                      {perShow[i].map((n) => (
                        <li key={n.id}>
                          <span className="pre">{n.text}</span>
                          {n.show_cue && noteWhere(n) && <span className="muted"> ({noteWhere(n)})</span>}
                          {n.follow_up && <p className="note-follow-up pre">{n.follow_up}</p>}
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              ))
            )}
          </div>
        ))}
      </section>

      {day.next_call.text && (
        <section>
          <h2>Next call</h2>
          <p className="pre">{day.next_call.text}</p>
        </section>
      )}

      <footer className="report-sign-off">
        {day.stage_managers && <p>Stage managers: {day.stage_managers}</p>}
        {day.contacts && <p className="pre muted">{day.contacts}</p>}
        <p className="muted">Report made {when(day.as_of)}.</p>
      </footer>
    </>
  )
}

/** The show report for one run, laid out to print (or save as PDF) from the browser. */
export default function Report({ productionId, runId }) {
  const [report, setReport] = useState(null)
  const [cues, setCues] = useState([])
  const [files, setFiles] = useState([])
  const [editingHeader, setEditingHeader] = useState(false)
  const [role, setRole] = useState(null)
  const [view, setView] = useState(storedView)
  // "day" or "show" once picked; until then the production's setting decides.
  const [scopeChoice, setScopeChoice] = useState(null)
  const [dayTitle, setDayTitle] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([api.report(runId), api.production(productionId), api.cues(productionId)])
      .then(([r, p, c]) => {
        if (cancelled) return
        if (r.production.id !== productionId) throw new Error('That run belongs to another production.')
        setReport(r)
        setRole(p.role)
        setCues(c)
        // Only to offer as attachments, so a failure here doesn't stop the report.
        api.files(productionId).then((f) => !cancelled && setFiles(f), () => {})
      })
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [productionId, runId])

  // After a note changes: the server works out each note's clock, scene and hold.
  const refresh = () =>
    api
      .report(runId)
      .then(setReport)
      .catch((e) => setError(e.message))

  // The browser's print dialog names the PDF after the page title.
  useEffect(() => {
    if (!report) return
    const before = document.title
    document.title = `Show report – ${report.production.name} – ${dayTitle || report.run.label}`
    return () => {
      document.title = before
    }
  }, [report, dayTitle])

  const back = (
    <Link className="account-link" to={`/productions/${productionId}/runs/${runId}`}>
      ← Back to the board
    </Link>
  )
  if (error)
    return (
      <main className="report">
        {back}
        <p className="error">{error}</p>
      </main>
    )
  if (!report) return <main className="report muted">Loading the report…</main>

  const { production, run, timing, holds, scenes } = report
  const late = lateness(timing.late_seconds)
  const canEdit = can(role, 'operate')
  // A run that shares its day with other shows can show the day's combined report.
  const scope = report.day ? (scopeChoice ?? (report.day.combined ? 'day' : 'show')) : 'show'
  function chooseView(key) {
    setView(key)
    try {
      localStorage.setItem(VIEW_KEY, key)
    } catch {
      // Remembering the view is a convenience; private windows may refuse.
    }
  }
  return (
    <main className="report">
      <div className="report-tools no-print">
        {back}
        <span className="spacer" />
        <button onClick={() => window.print()} title="Print, or choose Save as PDF in the print dialog">
          Print / Save as PDF
        </button>
      </div>
      {report.day && (
        <div className="report-scope no-print" role="group" aria-label="Report for">
          {[
            ['day', `Whole day (${report.day.shows.map((s) => s.title).join(', ')})`],
            ['show', `This show only`],
          ].map(([key, label]) => (
            <button
              key={key}
              className={`ghost small${scope === key ? ' on' : ''}`}
              aria-pressed={scope === key}
              onClick={() => {
                setScopeChoice(key)
                if (key === 'show') setDayTitle('')
              }}
            >
              {label}
            </button>
          ))}
        </div>
      )}
      {canEdit && (
        <div className="no-print">
          <EmailForm runId={runId} files={files} scope={report.day ? scope : undefined} />
        </div>
      )}

      {scope === 'day' ? (
        <article className="report-sheet">
          <DayReport runId={runId} onLoaded={(d) => setDayTitle(d.title)} />
        </article>
      ) : (
        <article className="report-sheet">
          <header>
            <p className="report-kicker">Show report</p>
            <h1>{production.name}</h1>
            <p className="report-headline">
              <strong>{report.header.line}</strong>
              {canEdit && !editingHeader && (
                <button className="ghost small no-print report-edit-toggle" onClick={() => setEditingHeader(true)}>
                  Edit
                </button>
              )}
            </p>
            {report.header.special_label && <p className="report-special">{report.header.special_label}</p>}
            {editingHeader && (
              <HeaderEdit
                runId={runId}
                run={run}
                header={report.header}
                stageManagers={report.stage_managers}
                onDone={(saved) => {
                  setEditingHeader(false)
                  if (saved) refresh()
                }}
              />
            )}
            <p>
              {[production.company, production.venue, formatDateRange(production.opening_date, production.closing_date)]
                .filter(Boolean)
                .join(' · ')}
            </p>
            <p>
              <strong>{run.label}</strong> · {run.kind}
            </p>
            {report.in_progress && <p className="report-warning">Still running: times are up to {when(report.as_of)}.</p>}
          </header>

          <dl className="report-summary">
            <dt>Scheduled</dt>
            <dd>{when(run.scheduled_start)}</dd>
            <dt>Started</dt>
            <dd>
              {run.started_at ? when(run.started_at) : 'Not started'}
              {late && ` (${late})`}
            </dd>
            <dt>Ended</dt>
            <dd>{run.ended_at ? when(run.ended_at) : 'Still running'}</dd>
            <dt>Running time</dt>
            <dd>
              {length(timing.running_seconds)}
              {timing.held_in_run_seconds > 0 && ` (${length(timing.held_in_run_seconds)} of it held)`}
            </dd>
            <dt>Holds</dt>
            <dd>
              {holds.count} {holds.count === 1 ? 'hold' : 'holds'}, {length(holds.total_seconds)} in all
            </dd>
            <dt>Cues fired</dt>
            <dd>{timing.cues_fired}</dd>
          </dl>

          <ActTimes runId={runId} block={report.acts} canEdit={canEdit} onChanged={refresh} />

          <section>
            <h2>Scenes</h2>
            {scenes.length === 0 ? (
              <p className="muted">No cues fired.</p>
            ) : (
              <table className="report-table">
                <thead>
                  <tr>
                    <th>Scene</th>
                    <th>From</th>
                    <th>Up</th>
                    <th className="num">Length</th>
                    <th className="num">Held</th>
                  </tr>
                </thead>
                <tbody>
                  {scenes.map((s, i) => (
                    <tr key={i}>
                      <td>{sceneName(s)}</td>
                      <td>{cueText(s.first_cue)}</td>
                      <td>{clockTime(s.started_at)}</td>
                      <td className="num">
                        {length(s.seconds)}
                        {!s.ended_at && report.in_progress && ' so far'}
                      </td>
                      <td className="num">{s.held_seconds ? length(s.held_seconds) : ''}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <h2>Holds</h2>
            {holds.items.length === 0 ? (
              <p className="muted">No holds.</p>
            ) : (
              <table className="report-table">
                <thead>
                  <tr>
                    <th>At</th>
                    <th className="num">Length</th>
                    <th>Reason</th>
                    <th>Cue</th>
                  </tr>
                </thead>
                <tbody>
                  {holds.items.map((h, i) => (
                    <tr key={i}>
                      <td>{clockTime(h.started_at)}</td>
                      <td className="num">
                        {length(h.seconds)}
                        {!h.resumed_at && ' (not resumed)'}
                      </td>
                      <td className="pre">{h.reason}</td>
                      <td>{cueText(h.cue_number)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>

          <section>
            <div className="row-between">
              <h2>Performance notes</h2>
              <div className="report-views no-print" role="group" aria-label="Report view">
                {[
                  ['working', 'Working view'],
                  ['distributed', 'Distributed'],
                ].map(([key, label]) => (
                  <button
                    key={key}
                    className={`ghost small${view === key ? ' on' : ''}`}
                    aria-pressed={view === key}
                    onClick={() => chooseView(key)}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>
            {view === 'working' ? (
              <WorkingNotes report={report} canEdit={canEdit} onChanged={refresh} />
            ) : (
              <DistributedNotes report={report} />
            )}
            {canEdit && (
              <AddLaterNote
                runId={runId}
                cues={cues}
                sections={report.sections}
                baseIso={run.started_at ?? run.scheduled_start ?? report.as_of}
                onAdded={refresh}
              />
            )}
          </section>

          <NextCall runId={runId} call={report.next_call} canEdit={canEdit} onChanged={refresh} />

          <footer className="report-sign-off">
            {report.stage_managers.names && <p>Stage managers: {report.stage_managers.names}</p>}
            {report.contacts && <p className="pre muted">{report.contacts}</p>}
            <p className="muted">Report made {when(report.as_of)}.</p>
          </footer>
        </article>
      )}
    </main>
  )
}
