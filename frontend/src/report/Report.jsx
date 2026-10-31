import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { can } from '../access'
import { findByNumber } from '../board/state'
import { formatDateRange } from '../dates'
import { cueText, lateness, length, noteMoment, noteWhere, parseAddresses, sceneName } from './reportText'

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

/** Send the report to a few addresses; operators and up. */
function EmailForm({ runId }) {
  const [text, setText] = useState('')
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
      setResult(await api.emailReport(runId, to))
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
      <button type="submit" disabled={busy || !parseAddresses(text).length}>
        {busy ? 'Sending…' : 'Email'}
      </button>
      {result && <p className="ok">Sent to {result.to.join(', ')}.</p>}
      {error && <p className="error">{error}</p>}
    </form>
  )
}

/**
 * The run's own notes: incidents and anything else for the report. Operators
 * edit them here; the printed page shows the text.
 */
function RunNotes({ runId, notes, canEdit, onSaved }) {
  const [draft, setDraft] = useState(notes)
  const [state, setState] = useState('')

  async function save(e) {
    e.preventDefault()
    setState('saving')
    try {
      const updated = await api.updateRun(runId, { notes: draft })
      onSaved(updated.notes)
      setState('saved')
    } catch (err) {
      setState(err.message)
    }
  }

  if (!canEdit) return notes ? <p className="pre">{notes}</p> : <p className="muted">None.</p>
  return (
    <>
      <form className="no-print report-notes-form" onSubmit={save}>
        <textarea
          rows={4}
          aria-label="Notes and incidents"
          placeholder="Incidents, late starts, anything else for the report"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value)
            setState('')
          }}
        />
        <div className="row">
          <button type="submit" className="small" disabled={draft === notes || state === 'saving'}>
            Save notes
          </button>
          {state === 'saved' && <span className="ok">Saved.</span>}
          {state && state !== 'saved' && state !== 'saving' && <span className="error">{state}</span>}
        </div>
      </form>
      <p className="pre print-only">{notes || 'None.'}</p>
    </>
  )
}

/**
 * One performance note: when and where it happened, the text written live,
 * and the follow-up written afterwards. Operators write the follow-up; the
 * live text stays as it was written.
 */
function PerformanceNote({ note, canEdit, onChanged }) {
  const [draft, setDraft] = useState(null) // null: not writing the follow-up
  const [error, setError] = useState('')
  const where = noteWhere(note)

  async function save(e) {
    e.preventDefault()
    setError('')
    try {
      await api.updateCueNote(note.id, { follow_up: draft.trim() })
      setDraft(null)
      onChanged()
    } catch (err) {
      setError(err.message)
    }
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
function AddLaterNote({ runId, cues, baseIso, onAdded }) {
  const [text, setText] = useState('')
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
        <button type="submit" className="small" disabled={!cueOk || !text.trim()}>
          Add note
        </button>
        {!cueOk && <span className="error">No Q{number} in the list.</span>}
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

/** The show report for one run, laid out to print (or save as PDF) from the browser. */
export default function Report({ productionId, runId }) {
  const [report, setReport] = useState(null)
  const [cues, setCues] = useState([])
  const [role, setRole] = useState(null)
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
    document.title = `Show report – ${report.production.name} – ${report.run.label}`
    return () => {
      document.title = before
    }
  }, [report])

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
  return (
    <main className="report">
      <div className="report-tools no-print">
        {back}
        <span className="spacer" />
        <button onClick={() => window.print()} title="Print, or choose Save as PDF in the print dialog">
          Print / Save as PDF
        </button>
      </div>
      {can(role, 'operate') && (
        <div className="no-print">
          <EmailForm runId={runId} />
        </div>
      )}

      <article className="report-sheet">
        <header>
          <p className="report-kicker">Show report</p>
          <h1>{production.name}</h1>
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
          <h2>Performance notes</h2>
          {report.performance_notes.length === 0 ? (
            <p className="muted">No performance notes.</p>
          ) : (
            <ol className="report-notes">
              {report.performance_notes.map((n) => (
                <PerformanceNote key={n.id} note={n} canEdit={can(role, 'operate')} onChanged={refresh} />
              ))}
            </ol>
          )}
          {can(role, 'operate') && (
            <AddLaterNote
              runId={runId}
              cues={cues}
              baseIso={run.started_at ?? run.scheduled_start ?? report.as_of}
              onAdded={refresh}
            />
          )}
        </section>

        <section>
          <h2>Notes and incidents</h2>
          <RunNotes
            runId={runId}
            notes={report.notes}
            canEdit={can(role, 'operate')}
            onSaved={(notes) => setReport((r) => ({ ...r, notes }))}
          />
        </section>

        <footer className="muted">Report made {when(report.as_of)}.</footer>
      </article>
    </main>
  )
}
