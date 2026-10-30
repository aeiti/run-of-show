import { useState } from 'react'
import { Link } from 'react-router'
import { CueNoteForm, CueNoteItem } from './CueNotes'
import { formatClock } from './playbackSteps'
import RunTimes from './RunTimes'
import { fromLocalInput } from '../dates'

const KINDS = ['rehearsal', 'tech', 'preview', 'performance', 'other']

// Dated by when the run was planned or happened, falling back to when it was made.
const runName = (r) =>
  [
    r.label,
    r.kind,
    new Date(r.scheduled_start ?? r.started_at ?? r.created_at).toLocaleDateString(),
    r.ended_at && 'ended',
  ]
    .filter(Boolean)
    .join(' · ')

const BLANK = { label: '', kind: 'rehearsal', scheduled_start: '' }

function logText(events, i) {
  const e = events[i]
  if (e.action === 'hold') return [e.note, e.cue_number && `at Q${e.cue_number}`].filter(Boolean).join(' · ')
  if (e.action === 'resume') {
    const held = events.slice(0, i).findLast((x) => x.action === 'hold')
    return held ? `after ${formatClock((Date.parse(e.fired_at) - Date.parse(held.fired_at)) / 1000)}` : ''
  }
  return e.action === 'reset' ? '' : `Q${e.cue_number} ${e.cue_label}`
}

/** Events and cue notes in one list, in time order. */
function logItems(events, notes) {
  const items = [
    ...events.map((e, i) => ({ key: `e${e.id}`, at: e.fired_at, i })),
    ...notes.map((n) => ({ key: `n${n.id}`, at: n.created_at, note: n })),
  ]
  return items.sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
}

/** Pick, start or end a run, write cue notes, and show its log. */
export default function RunPanel({
  runs,
  run,
  cues,
  canOperate,
  noteCueNumber,
  noteRef,
  onSelect,
  onCreate,
  onEnd,
  onUpdate,
  onExport,
  onAddNote,
  onEditNote,
  onDeleteNote,
}) {
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState(BLANK)
  const [confirmEnd, setConfirmEnd] = useState(false)

  async function create(e) {
    e.preventDefault()
    if (
      await onCreate({ ...draft, label: draft.label.trim(), scheduled_start: fromLocalInput(draft.scheduled_start) })
    ) {
      setCreating(false)
      setDraft(BLANK)
    }
  }

  function end() {
    if (!confirmEnd) {
      setConfirmEnd(true)
      setTimeout(() => setConfirmEnd(false), 3000)
      return
    }
    setConfirmEnd(false)
    onEnd()
  }

  const events = run?.events ?? []
  const notes = run?.cue_notes ?? []

  return (
    <section className="run-panel">
      <h3>Run</h3>
      <div className="row">
        <select
          aria-label="Run"
          value={run?.id ?? ''}
          onChange={(e) => onSelect(Number(e.target.value))}
          disabled={!runs.length}
        >
          {runs.map((r) => (
            <option key={r.id} value={r.id}>
              {runName(r)}
            </option>
          ))}
        </select>
        {canOperate && (
          <button className="ghost" onClick={() => setCreating(!creating)}>
            {creating ? 'Cancel' : 'New'}
          </button>
        )}
      </div>

      {creating && (
        <form className="new-run" onSubmit={create}>
          <div className="row">
            <input
              required
              autoFocus
              aria-label="New run label"
              placeholder="Preview 2"
              value={draft.label}
              onChange={(e) => setDraft({ ...draft, label: e.target.value })}
            />
            <select aria-label="Kind" value={draft.kind} onChange={(e) => setDraft({ ...draft, kind: e.target.value })}>
              {KINDS.map((k) => (
                <option key={k}>{k}</option>
              ))}
            </select>
          </div>
          <div className="row">
            <input
              type="datetime-local"
              aria-label="Scheduled start (optional)"
              title="Scheduled start (optional)"
              value={draft.scheduled_start}
              onChange={(e) => setDraft({ ...draft, scheduled_start: e.target.value })}
            />
            <button type="submit">Start</button>
          </div>
        </form>
      )}

      {run && <RunTimes key={run.id} run={run} canEdit={canOperate} onSave={onUpdate} />}

      {run?.ended_at ? (
        <p className="muted ended">
          Ended {new Date(run.ended_at).toLocaleString()}.{canOperate && ' Start a new run to keep going.'}
        </p>
      ) : (
        run &&
        canOperate && (
          <button className={`ghost small ${confirmEnd ? 'danger' : ''}`} onClick={end}>
            {confirmEnd ? 'Confirm: end this run' : 'End run'}
          </button>
        )
      )}

      <div className="row-between">
        <h3>Log · {run?.label}</h3>
        {run && (
          <div className="row log-tools">
            <Link
              className="button ghost small"
              to={`/productions/${run.production}/runs/${run.id}/report`}
              title="Times, holds, scene lengths and notes, to print or email"
            >
              Report
            </Link>
            <button className="ghost small" onClick={() => onExport(run.id)}>
              Export
            </button>
          </div>
        )}
      </div>
      {run && canOperate && (
        <CueNoteForm cues={cues} defaultNumber={noteCueNumber} disabled={!run} onAdd={onAddNote} inputRef={noteRef} />
      )}
      <ol className="log">
        {events.length === 0 && notes.length === 0 && <li className="muted">Nothing fired in this run yet.</li>}
        {logItems(events, notes).map(({ key, i, note }) =>
          note ? (
            <CueNoteItem key={key} note={note} canEdit={canOperate} onEdit={onEditNote} onDelete={onDeleteNote} />
          ) : (
            <li key={key}>
              <time>{new Date(events[i].fired_at).toLocaleTimeString()}</time>
              {events[i].action !== 'go' && <b className="log-action">{events[i].action.toUpperCase()} </b>}
              {logText(events, i)}
            </li>
          ),
        )}
      </ol>
    </section>
  )
}
