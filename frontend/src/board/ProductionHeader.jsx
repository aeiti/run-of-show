import { useState } from 'react'
import { api } from '../api'
import { can, ROLES } from '../access'
import { formatDateRange } from '../dates'

const FIELDS = ['name', 'company', 'venue', 'opening_date', 'closing_date', 'notes']

export default function ProductionHeader({ production, onSaved, onDeleted, onPeople }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [confirmName, setConfirmName] = useState(null)
  const [error, setError] = useState('')

  if (!production) return <h2>…</h2>

  function start() {
    setDraft(Object.fromEntries(FIELDS.map((f) => [f, production[f] ?? ''])))
    setConfirmName(null)
    setError('')
    setEditing(true)
  }

  async function save(e) {
    e.preventDefault()
    try {
      const dates = { opening_date: draft.opening_date || null, closing_date: draft.closing_date || null }
      onSaved(await api.updateProduction(production.id, { ...draft, ...dates }))
      setEditing(false)
    } catch (err) {
      setError(err.message)
    }
  }

  async function remove() {
    try {
      await api.deleteProduction(production.id)
      onDeleted()
    } catch (err) {
      setError(err.message)
    }
  }

  if (!editing) {
    return (
      <div className="production-header">
        <div className="row-between">
          <h2>{production.name}</h2>
          <div className="row header-actions">
            <button className="ghost small" onClick={onPeople}>
              People
            </button>
            {can(production.role, 'edit') && (
              <button className="ghost small" onClick={start}>
                Edit details
              </button>
            )}
          </div>
        </div>
        <p className="muted">
          {[production.company, production.venue, formatDateRange(production.opening_date, production.closing_date)]
            .filter(Boolean)
            .join(' · ')}
        </p>
        {production.role !== 'owner' && (
          <p className="muted shared-by">
            {ROLES[production.role]} · shared by {production.owner.display_name || production.owner.username}
          </p>
        )}
        {production.notes && <p className="production-notes">{production.notes}</p>}
      </div>
    )
  }

  const field = (key) => ({ value: draft[key], onChange: (e) => setDraft({ ...draft, [key]: e.target.value }) })

  return (
    <form className="production-header panel editing" onSubmit={save}>
      <div className="field-grid">
        <label>
          Name
          <input required autoFocus {...field('name')} />
        </label>
        <label>
          Company
          <input {...field('company')} />
        </label>
        <label>
          Venue
          <input {...field('venue')} />
        </label>
        <label>
          Opens
          <input type="date" {...field('opening_date')} />
        </label>
        <label>
          Closes
          <input type="date" min={draft.opening_date || undefined} {...field('closing_date')} />
        </label>
        <label className="span-all">
          Notes
          <textarea rows={2} {...field('notes')} />
        </label>
      </div>
      <div className="row">
        <button type="submit">Save</button>
        <button type="button" className="ghost" onClick={() => setEditing(false)}>
          Cancel
        </button>
        <span className="spacer" />
        {!can(production.role, 'delete') ? null : confirmName === null ? (
          <button type="button" className="ghost danger" onClick={() => setConfirmName('')}>
            Delete production…
          </button>
        ) : (
          <>
            <input
              aria-label="Type the production name to confirm"
              placeholder={`Type “${production.name}” to delete`}
              value={confirmName}
              onChange={(e) => setConfirmName(e.target.value)}
            />
            <button type="button" className="danger" disabled={confirmName !== production.name} onClick={remove}>
              Delete
            </button>
          </>
        )}
      </div>
      {confirmName !== null && (
        <p className="muted small-print">This deletes every cue, run and log entry in the production.</p>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  )
}
