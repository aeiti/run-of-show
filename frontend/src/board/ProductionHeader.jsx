import { useState } from 'react'
import { api } from '../api'
import { can, ROLES } from '../access'
import ProductionLogo from '../ProductionLogo'
import LogoField from './LogoField'
import { formatDateRange } from '../dates'
import { formatCallTemplate, parseCallTemplate } from '../report/reportText'

const FIELDS = ['name', 'company', 'venue', 'opening_date', 'closing_date', 'notes', 'contacts']

// onScript is null when there is no script to show.
export default function ProductionHeader({ production, onSaved, onDeleted, onPeople, onFiles, onScript, scriptShown }) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(null)
  const [confirmName, setConfirmName] = useState(null)
  const [error, setError] = useState('')

  if (!production) return <h2>…</h2>

  function start() {
    // The note sections are edited one per line.
    const sections = (production.note_sections ?? []).join('\n')
    setDraft({
      ...Object.fromEntries(FIELDS.map((f) => [f, production[f] ?? ''])),
      note_sections: sections,
      call_template: formatCallTemplate(production.call_template ?? []),
      combined_reports: production.combined_reports ?? true,
    })
    setConfirmName(null)
    setError('')
    setEditing(true)
  }

  async function save(e) {
    e.preventDefault()
    try {
      const dates = { opening_date: draft.opening_date || null, closing_date: draft.closing_date || null }
      const note_sections = draft.note_sections.split('\n')
      const { calls, bad } = parseCallTemplate(draft.call_template)
      if (bad.length) {
        setError(`Start each call with the minutes before curtain: "${bad[0]}"`)
        return
      }
      onSaved(await api.updateProduction(production.id, { ...draft, ...dates, note_sections, call_template: calls }))
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
          <h2 className="production-title">
            <ProductionLogo production={production} />
            {production.name}
          </h2>
          <div className="row header-actions">
            {onScript && (
              <button className={`ghost small${scriptShown ? ' on' : ''}`} aria-pressed={scriptShown} onClick={onScript}>
                Script
              </button>
            )}
            <button className="ghost small" onClick={onFiles}>
              Files
            </button>
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
        <label className="span-all">
          Report note sections, one per line, in order
          <textarea rows={5} {...field('note_sections')} />
        </label>
        <label className="span-all">
          Next call: minutes before curtain and what happens, one per line
          <textarea rows={4} placeholder={'45 Wig prep starts\n30 Half hour – House open'} {...field('call_template')} />
        </label>
        <label className="span-all">
          Stage management contacts, printed at the foot of each report
          <textarea rows={3} placeholder="PSM: name, phone, email" {...field('contacts')} />
        </label>
        <label className="span-all checkbox">
          <input
            type="checkbox"
            checked={draft.combined_reports}
            onChange={(e) => setDraft({ ...draft, combined_reports: e.target.checked })}
          />
          One report for a two-show day (otherwise one report per show)
        </label>
        <LogoField production={production} onSaved={onSaved} />
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
