import { useState } from 'react'
import { api } from '../api'

const COLUMNS = [
  { key: 'number', label: '#', className: 'narrow', required: true },
  { key: 'label', label: 'Label' },
  { key: 'page', label: 'Pg', className: 'narrow', inputMode: 'numeric' },
  { key: 'scene', label: 'Scene' },
  { key: 'notes', label: 'Notes', className: 'wide' },
]

// The API wants a number or null for page; the inputs hold strings.
const toApi = (key, value) => (key === 'page' ? (value === '' ? null : Number(value)) : value)
const toInput = (value) => (value == null ? '' : String(value))

/** Inline cue editing: each field saves on Enter or when it loses focus; Esc puts it back. */
export default function CueEditor({ cues, productionId, onSaved, onCreated, onDeleted }) {
  return (
    <div className="cue-editor">
      <div className="editor-head" aria-hidden="true">
        {COLUMNS.map((c) => (
          <span key={c.key} className={c.className}>
            {c.label}
          </span>
        ))}
        <span className="actions" />
      </div>
      <ol className="editor-rows">
        {cues.map((cue) => (
          <CueRow key={cue.id} cue={cue} onSaved={onSaved} onDeleted={onDeleted} />
        ))}
      </ol>
      <NewCueRow productionId={productionId} onCreated={onCreated} />
    </div>
  )
}

function CueRow({ cue, onSaved, onDeleted }) {
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  async function commit(key, input) {
    const value = toApi(key, input.value)
    if (toInput(value) === toInput(cue[key])) return
    try {
      setError('')
      onSaved(await api.updateCue(cue.id, { [key]: value }))
    } catch (err) {
      setError(err.message)
      input.value = toInput(cue[key])
    }
  }

  async function remove() {
    if (!confirming) {
      setConfirming(true)
      setTimeout(() => setConfirming(false), 3000)
      return
    }
    try {
      await api.deleteCue(cue.id)
      onDeleted(cue.id)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <li className="editor-row">
      {COLUMNS.map((c) => (
        <input
          // Re-mount when the saved value changes so the uncontrolled input shows it.
          key={`${c.key}:${toInput(cue[c.key])}`}
          aria-label={`Cue ${cue.number} ${c.label}`}
          className={c.className}
          inputMode={c.inputMode}
          required={c.required}
          defaultValue={toInput(cue[c.key])}
          onBlur={(e) => commit(c.key, e.target)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.target.blur()
            if (e.key === 'Escape') {
              e.target.value = toInput(cue[c.key])
              e.target.blur()
            }
          }}
        />
      ))}
      <button className={`ghost small actions ${confirming ? 'danger' : ''}`} onClick={remove}>
        {confirming ? 'Confirm' : 'Delete'}
      </button>
      {error && <p className="error row-error">{error}</p>}
    </li>
  )
}

const BLANK = { number: '', label: '', page: '', scene: '', notes: '' }

function NewCueRow({ productionId, onCreated }) {
  const [draft, setDraft] = useState(BLANK)
  const [error, setError] = useState('')

  async function add(e) {
    e.preventDefault()
    try {
      setError('')
      const body = Object.fromEntries(Object.entries(draft).map(([k, v]) => [k, toApi(k, v)]))
      onCreated(await api.createCue(productionId, body))
      setDraft(BLANK)
      e.target.querySelector('input').focus()
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="editor-row new-row" onSubmit={add}>
      {COLUMNS.map((c) => (
        <input
          key={c.key}
          aria-label={`New cue ${c.label}`}
          placeholder={c.key === 'number' ? 'New' : c.label}
          className={c.className}
          inputMode={c.inputMode}
          required={c.required}
          value={draft[c.key]}
          onChange={(e) => setDraft({ ...draft, [c.key]: e.target.value })}
        />
      ))}
      <button type="submit" className="ghost small actions">
        Add
      </button>
      {error && <p className="error row-error">{error}</p>}
    </form>
  )
}
