import { useState } from 'react'
import { findByNumber } from './state'

/**
 * Write a performance note in this run ("Q12 late", "big laugh on the bell").
 * The cue box follows the loaded or active cue until it is typed in, and may
 * be left empty: before the first GO, at the act break, or for a note about
 * no cue in particular. The server stamps the time.
 *
 * The section stays as picked for the next note. In the note box, Alt+1 to
 * Alt+9 pick the production's first nine sections and Alt+0 none.
 */
export function CueNoteForm({ cues, sections = [], defaultNumber, disabled, onAdd, inputRef }) {
  const [typed, setTyped] = useState(null) // null: follow defaultNumber
  const [text, setText] = useState('')
  const [section, setSection] = useState('')
  const number = typed ?? defaultNumber ?? ''
  const cue = findByNumber(cues, number)
  // An empty box is no cue; a number that isn't in the list can't be saved.
  const cueOk = !String(number).trim() || cue

  async function submit(e) {
    e.preventDefault()
    if (!cueOk || !text.trim()) return
    if (await onAdd(cue?.id ?? null, text.trim(), sections.includes(section) ? section : '')) {
      setText('')
      setTyped(null)
      inputRef.current?.blur()
    }
  }

  return (
    <form className="row note-form" onSubmit={submit}>
      <input
        className="narrow"
        aria-label="Cue the note is about (optional)"
        placeholder="Q#"
        inputMode="decimal"
        value={number}
        onChange={(e) => setTyped(e.target.value)}
      />
      <input
        ref={inputRef}
        aria-label="Note"
        placeholder={cue ? `Note at Q${cue.number}` : cueOk ? 'Performance note' : `No Q${number} in the list`}
        maxLength={2000}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          // By key position: Alt with a digit types another character on a Mac.
          const digit = e.altKey && /^Digit(\d)$/.exec(e.code)?.[1]
          if (!digit) return
          e.preventDefault()
          setSection(digit === '0' ? '' : (sections[Number(digit) - 1] ?? section))
        }}
      />
      {sections.length > 0 && (
        <select
          className="note-section"
          aria-label="Section"
          title="Alt+1 to Alt+9 in the note box pick a section, Alt+0 none"
          value={sections.includes(section) ? section : ''}
          onChange={(e) => setSection(e.target.value)}
        >
          <option value="">No section</option>
          {sections.map((name) => (
            <option key={name}>{name}</option>
          ))}
        </select>
      )}
      <button type="submit" className="ghost" disabled={disabled || !cueOk || !text.trim()} title="N to write a note">
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
      {/* A note added later from the report is shown at the time chosen for it. */}
      <time>{new Date(note.at ?? note.created_at).toLocaleTimeString()}</time>
      <b className="log-action">NOTE </b>
      {note.cue_number && `Q${note.cue_number} `}
      {note.section && <span className="muted">[{note.section}] </span>}
      {draft === null ? (
        <>
          {note.text}
          {note.author && <span className="muted"> · {note.author}</span>}
          {note.added_later && <span className="muted"> · added later</span>}
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
