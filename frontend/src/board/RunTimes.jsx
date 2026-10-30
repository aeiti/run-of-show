import { useEffect, useState } from 'react'
import { formatLateness, fromLocalInput, keepSeconds, minutesLate, secondsBetween, toLocalInput } from '../dates'
import { formatClock } from './playbackSteps'

/** A clock that ticks once a second while `running`, so a live run's length counts up. */
function useNow(running) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!running) return
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [running])
  return now
}

/** "19:30" today, "14 Mar, 19:30" on another day. */
function when(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const time = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  if (d.toDateString() === new Date().toDateString()) return time
  return `${d.toLocaleDateString([], { day: 'numeric', month: 'short' })}, ${time}`
}

const FIELDS = [
  ['scheduled_start', 'Scheduled'],
  ['started_at', 'Started'],
  ['ended_at', 'Ended'],
]

/** Scheduled and actual start, end and running length; operators can correct them. */
export default function RunTimes({ run, canEdit, onSave }) {
  const [draft, setDraft] = useState(null)
  const now = useNow(Boolean(run.started_at && !run.ended_at))
  const length = secondsBetween(run.started_at, run.ended_at, now)
  const late = minutesLate(run.scheduled_start, run.started_at)
  // The end is only set by End run, so it can be corrected but not added here.
  const fields = FIELDS.filter(([key]) => key !== 'ended_at' || run.ended_at)

  function start() {
    setDraft(Object.fromEntries(fields.map(([key]) => [key, toLocalInput(run[key])])))
  }

  async function save(e) {
    e.preventDefault()
    const body = {}
    for (const [key] of fields) {
      const value = keepSeconds(run[key], fromLocalInput(draft[key]))
      if (value !== run[key]) body[key] = value
    }
    if (!Object.keys(body).length || (await onSave(body))) setDraft(null)
  }

  if (draft) {
    return (
      <form className="run-times-form" onSubmit={save}>
        {fields.map(([key, label]) => (
          <label key={key}>
            {label}
            <input
              type="datetime-local"
              value={draft[key]}
              required={key === 'ended_at'}
              onChange={(e) => setDraft({ ...draft, [key]: e.target.value })}
            />
          </label>
        ))}
        <div className="row">
          <button type="submit" className="small">
            Save
          </button>
          <button type="button" className="ghost small" onClick={() => setDraft(null)}>
            Cancel
          </button>
        </div>
      </form>
    )
  }

  return (
    <div className="run-times">
      <dl>
        <dt>Scheduled</dt>
        <dd title={run.scheduled_start ? new Date(run.scheduled_start).toLocaleString() : undefined}>
          {when(run.scheduled_start) || '—'}
        </dd>
        <dt>Started</dt>
        <dd title={run.started_at ? new Date(run.started_at).toLocaleString() : undefined}>
          {when(run.started_at) || 'not yet'}
          {late !== null && <span className={late > 0 ? 'late' : 'muted'}> {formatLateness(late)}</span>}
        </dd>
        <dt>Ended</dt>
        <dd title={run.ended_at ? new Date(run.ended_at).toLocaleString() : undefined}>
          {run.ended_at ? when(run.ended_at) : run.started_at ? 'running' : '—'}
        </dd>
        <dt>Length</dt>
        <dd className="clock-value">{length === null ? '—' : formatClock(length)}</dd>
      </dl>
      {canEdit && (
        <button className="ghost small" onClick={start} title="Correct the scheduled or actual times">
          Edit times
        </button>
      )}
    </div>
  )
}
