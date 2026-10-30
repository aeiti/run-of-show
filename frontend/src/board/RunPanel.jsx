import { useState } from 'react'

const KINDS = ['rehearsal', 'tech', 'preview', 'performance', 'other']

const runName = (r) =>
  [r.label, r.kind, new Date(r.created_at).toLocaleDateString(), r.ended_at && 'ended'].filter(Boolean).join(' · ')

/** Pick, start or end a run, and show its log. */
export default function RunPanel({ runs, run, onSelect, onCreate, onEnd }) {
  const [creating, setCreating] = useState(false)
  const [draft, setDraft] = useState({ label: '', kind: 'rehearsal' })
  const [confirmEnd, setConfirmEnd] = useState(false)

  async function create(e) {
    e.preventDefault()
    if (await onCreate({ ...draft, label: draft.label.trim() })) {
      setCreating(false)
      setDraft({ label: '', kind: 'rehearsal' })
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
        <button className="ghost" onClick={() => setCreating(!creating)}>
          {creating ? 'Cancel' : 'New'}
        </button>
      </div>

      {creating && (
        <form className="row" onSubmit={create}>
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
          <button type="submit">Start</button>
        </form>
      )}

      {run?.ended_at ? (
        <p className="muted ended">Ended {new Date(run.ended_at).toLocaleString()}. Start a new run to keep going.</p>
      ) : (
        run && (
          <button className={`ghost small ${confirmEnd ? 'danger' : ''}`} onClick={end}>
            {confirmEnd ? 'Confirm: end this run' : 'End run'}
          </button>
        )
      )}

      <h3>Log · {run?.label}</h3>
      <ol className="log">
        {events.length === 0 && <li className="muted">Nothing fired in this run yet.</li>}
        {events.map((e) => (
          <li key={e.id}>
            <time>{new Date(e.fired_at).toLocaleTimeString()}</time>
            {e.action !== 'go' && <b className="log-action">{e.action.toUpperCase()} </b>}
            {e.action !== 'reset' && `Q${e.cue_number} ${e.cue_label}`}
          </li>
        ))}
      </ol>
    </section>
  )
}
