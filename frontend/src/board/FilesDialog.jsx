import { useState } from 'react'
import { api } from '../api'
import { can } from '../access'
import { formatSize, groupFiles, KINDS } from './files'

const uploadedOn = (f) => new Date(f.uploaded_at).toLocaleDateString()

/**
 * The production's scripts, showfiles and other files. Everyone on the
 * production can download any version; owners and stage managers upload and
 * delete. Uploading a file with the same kind and name adds a version.
 */
export default function FilesDialog({ production, files, onChange, onClose }) {
  const [kind, setKind] = useState('script')
  const [open, setOpen] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const editing = can(production.role, 'edit')

  async function run(fn) {
    setBusy(true)
    setError('')
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function upload(e) {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    form.append('kind', kind)
    run(async () => onChange([await api.uploadFile(production.id, form), ...files]))
  }

  function remove(f) {
    if (confirmDelete !== f.id) {
      setConfirmDelete(f.id)
      return
    }
    run(async () => {
      await api.deleteFile(f.id)
      setConfirmDelete(null)
      onChange(files.filter((x) => x.id !== f.id))
    })
  }

  const version = (f) => (
    <li key={f.id} className="file-version">
      <span className="muted">
        v{f.version} · {formatSize(f.size)} · {uploadedOn(f)}
        {f.uploaded_by && ` · ${f.uploaded_by}`}
      </span>
      <button className="ghost small" onClick={() => api.downloadFile(f).catch((err) => setError(err.message))}>
        Download
      </button>
      {editing && (
        <button
          className={`ghost small ${confirmDelete === f.id ? 'danger' : ''}`}
          disabled={busy}
          onClick={() => remove(f)}
          onBlur={() => setConfirmDelete(null)}
        >
          {confirmDelete === f.id ? 'Confirm' : 'Delete'}
        </button>
      )}
    </li>
  )

  const groups = groupFiles(files)

  return (
    <div className="dialog-backdrop" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="dialog files panel" role="dialog" aria-modal="true" aria-labelledby="files-title">
        <div className="row-between">
          <h2 id="files-title">Files</h2>
          <button className="ghost small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted small-print">
          The script (a PDF) can be shown beside the cue list, at the page of the active cue. Uploading a file with the
          same name and kind again keeps the earlier versions.
        </p>

        {groups.length === 0 && <p className="muted files-empty">No files yet.</p>}
        <ul className="file-list">
          {groups.map((g) => {
            const key = `${g.kind}/${g.name}`
            const [latest, ...older] = g.versions
            return (
              <li key={key}>
                <div className="file-name">
                  <strong>{g.name}</strong>
                  <span className="chip">{KINDS[g.kind]}</span>
                </div>
                <ul className="file-versions">
                  {version(latest)}
                  {open === key && older.map(version)}
                </ul>
                {older.length > 0 && (
                  <button className="ghost small" onClick={() => setOpen(open === key ? null : key)}>
                    {open === key ? 'Hide earlier versions' : `Earlier versions (${older.length})`}
                  </button>
                )}
              </li>
            )
          })}
        </ul>

        {editing && (
          <div className="row file-upload">
            <select aria-label="Kind of file" value={kind} onChange={(e) => setKind(e.target.value)}>
              {Object.entries(KINDS).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
            <input
              type="file"
              aria-label="Upload a file"
              accept={kind === 'script' ? '.pdf,application/pdf' : undefined}
              disabled={busy}
              onChange={upload}
            />
          </div>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  )
}
