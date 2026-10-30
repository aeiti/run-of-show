import { useState } from 'react'
import { api } from '../api'
import { formatTime, parseTimeInput } from './cueTime'

const toInput = (value) => (value == null ? '' : String(value))

// Each column reads its text from a cue and turns typed text into API fields.
// Most map one-to-one; Time is up and down in one box, as on Eos ("5/3").
const plain = (key) => ({ get: (cue) => toInput(cue[key]), put: (text) => ({ [key]: text }) })

const COLUMNS = [
  { key: 'number', label: '#', className: 'narrow', required: true, ...plain('number') },
  { key: 'label', label: 'Label', ...plain('label') },
  {
    key: 'time',
    label: 'Time',
    className: 'narrow',
    placeholder: '5/3',
    get: formatTime,
    put: parseTimeInput,
  },
  { key: 'follow', label: 'F/H', className: 'narrow', placeholder: 'F2', ...plain('follow') },
  {
    key: 'page',
    label: 'Pg',
    className: 'narrow',
    inputMode: 'numeric',
    get: (cue) => toInput(cue.page),
    put: (text) => ({ page: text === '' ? null : Number(text) }), // the API wants a number or null
  },
  { key: 'scene', label: 'Scene', ...plain('scene') },
  { key: 'notes', label: 'Notes', className: 'wide', ...plain('notes') },
]

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

  async function commit(column, input) {
    if (input.value.trim() === column.get(cue).trim()) return
    try {
      setError('')
      onSaved(await api.updateCue(cue.id, column.put(input.value)))
    } catch (err) {
      setError(err.message)
      input.value = column.get(cue)
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
          key={`${c.key}:${c.get(cue)}`}
          aria-label={`Cue ${cue.number} ${c.label}`}
          className={c.className}
          inputMode={c.inputMode}
          required={c.required}
          defaultValue={c.get(cue)}
          onBlur={(e) => commit(c, e.target)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') e.target.blur()
            if (e.key === 'Escape') {
              e.target.value = c.get(cue)
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

const BLANK = Object.fromEntries(COLUMNS.map((c) => [c.key, '']))

function NewCueRow({ productionId, onCreated }) {
  const [draft, setDraft] = useState(BLANK)
  const [error, setError] = useState('')

  async function add(e) {
    e.preventDefault()
    try {
      setError('')
      const body = Object.assign({}, ...COLUMNS.map((c) => c.put(draft[c.key])))
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
          placeholder={c.key === 'number' ? 'New' : (c.placeholder ?? c.label)}
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
