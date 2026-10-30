import { useEffect, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { can } from '../access'
import { formatDateRange } from '../dates'
import { cueText, lateness, length, parseAddresses, sceneName } from './reportText'

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

/** The show report for one run, laid out to print (or save as PDF) from the browser. */
export default function Report({ productionId, runId }) {
  const [report, setReport] = useState(null)
  const [role, setRole] = useState(null)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    Promise.all([api.report(runId), api.production(productionId)])
      .then(([r, p]) => {
        if (cancelled) return
        if (r.production.id !== productionId) throw new Error('That run belongs to another production.')
        setReport(r)
        setRole(p.role)
      })
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [productionId, runId])

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
          <h2>Cue notes</h2>
          {report.cue_notes.length === 0 ? (
            <p className="muted">No cue notes.</p>
          ) : (
            <ul className="report-notes">
              {report.cue_notes.map((n, i) => (
                <li key={i}>
                  <strong>{cueText(n.cue_number, n.cue_label)}</strong>: <span className="pre">{n.text}</span>
                  {n.author && <span className="muted"> ({n.author})</span>}
                </li>
              ))}
            </ul>
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
