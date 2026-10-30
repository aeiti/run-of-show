import { useState } from 'react'
import { findByNumber } from './state'

/**
 * Add a note about a cue in this run ("Q12 late, tech 2"). The cue box
 * follows the loaded or active cue until it is typed in.
 */
export function CueNoteForm({ cues, defaultNumber, disabled, onAdd, inputRef }) {
  const [typed, setTyped] = useState(null) // null: follow defaultNumber
  const [text, setText] = useState('')
  const number = typed ?? defaultNumber ?? ''
  const cue = findByNumber(cues, number)

  async function submit(e) {
    e.preventDefault()
    if (!cue || !text.trim()) return
    if (await onAdd(cue.id, text.trim())) {
      setText('')
      setTyped(null)
      inputRef.current?.blur()
    }
  }

  return (
    <form className="row note-form" onSubmit={submit}>
      <input
        className="narrow"
        aria-label="Cue the note is about"
        placeholder="Q#"
        inputMode="decimal"
        value={number}
        onChange={(e) => setTyped(e.target.value)}
      />
      <input
        ref={inputRef}
        aria-label="Note"
        placeholder={cue ? `Note on Q${cue.number}` : 'Note on a cue'}
        maxLength={2000}
        value={text}
        onChange={(e) => setText(e.target.value)}
      />
      <button type="submit" className="ghost" disabled={disabled || !cue || !text.trim()} title="N to write a note">
        Note
      </button>
    </form>
  )
}

/** One note in the log, with edit and delete for those who can. */
export function CueNoteItem({ note, canEdit, onEdit, onDelete }) {
  const [draft, setDraft] = useState(null) // null: not editing
  const [confirmDelete, setConfirmDelete] = useState(false)

  async function save(e) {
    e.preventDefault()
    if (draft.trim() && (await onEdit(note.id, draft.trim()))) setDraft(null)
  }

  function remove() {
    if (!confirmDelete) {
      setConfirmDelete(true)
      setTimeout(() => setConfirmDelete(false), 3000)
      return
    }
    onDelete(note.id)
  }

  return (
    <li className="log-note">
      <time>{new Date(note.created_at).toLocaleTimeString()}</time>
      <b className="log-action">NOTE </b>Q{note.cue_number}{' '}
      {draft === null ? (
        <>
          {note.text}
          {note.author && <span className="muted"> · {note.author}</span>}
          {canEdit && (
            <span className="note-tools">
              <button className="ghost small" onClick={() => setDraft(note.text)}>
                Edit
              </button>
              <button className={`ghost small ${confirmDelete ? 'danger' : ''}`} onClick={remove}>
                {confirmDelete ? 'Confirm' : 'Delete'}
              </button>
            </span>
          )}
        </>
      ) : (
        <form className="row" onSubmit={save}>
          <input
            autoFocus
            aria-label="Edit note"
            maxLength={2000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => e.key === 'Escape' && setDraft(null)}
          />
          <button type="submit" className="ghost small" disabled={!draft.trim()}>
            Save
          </button>
        </form>
      )}
    </li>
  )
}
