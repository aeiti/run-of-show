import { useState } from 'react'
import { api } from '../api'

const ACTIONS = ['create', 'update', 'unchanged', 'delete', 'reject']

/**
 * Import a cue list from a CSV file or pasted text. Every change is shown as
 * a dry run first; nothing is written until Import is pressed, and the
 * server re-plans against the current cue list at that point.
 */
export default function ImportDialog({ productionId, onImported, onClose }) {
  const [file, setFile] = useState(null)
  const [text, setText] = useState('')
  const [mode, setMode] = useState('merge')
  const [list, setList] = useState('')
  const [plan, setPlan] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  function form(dryRun, overrides = {}) {
    const data = new FormData()
    if (file) data.append('file', file)
    else data.append('text', text)
    data.append('mode', overrides.mode ?? mode)
    const chosen = overrides.list ?? list
    if (chosen) data.append('list', chosen)
    data.append('dry_run', dryRun ? 'true' : 'false')
    return data
  }

  async function preview(overrides) {
    setBusy(true)
    setError('')
    try {
      const result = await api.importCues(productionId, form(true, overrides))
      setPlan(result)
      if (result.list) setList(result.list)
    } catch (err) {
      setPlan(null)
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function confirm() {
    setBusy(true)
    setError('')
    try {
      const result = await api.importCues(productionId, form(false))
      onImported(result)
    } catch (err) {
      setError(err.message)
      setBusy(false)
    }
  }

  const changes = plan?.rows?.filter((r) => r.action !== 'unchanged') ?? []
  const writes = plan?.summary ? plan.summary.create + plan.summary.update + plan.summary.delete : 0

  return (
    <div className="dialog-backdrop" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="dialog panel" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="row-between">
          <h2 id="import-title">Import cues</h2>
          <button className="ghost small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted small-print">
          A CSV with a <code>number</code> column (and optionally <code>label</code>, <code>page</code>,{' '}
          <code>scene</code>, <code>notes</code>), or an ETC Eos CSV export, cues only or the whole show.
        </p>

        <div className="field-grid">
          <label>
            File
            <input
              type="file"
              accept=".csv,text/csv,text/plain"
              onChange={(e) => {
                setFile(e.target.files[0] ?? null)
                setPlan(null)
                setList('')
              }}
            />
          </label>
          <label>
            Mode
            <select
              value={mode}
              onChange={(e) => {
                setMode(e.target.value)
                if (plan) preview({ mode: e.target.value })
              }}
            >
              <option value="merge">Merge: add and update; never blanks a field</option>
              <option value="replace">Replace: the file becomes the cue list</option>
            </select>
          </label>
        </div>
        {!file && (
          <label>
            …or paste CSV
            <textarea
              rows={4}
              value={text}
              placeholder={'number,label,page\n1,Preset,1\n2,House out,1'}
              onChange={(e) => {
                setText(e.target.value)
                setPlan(null)
              }}
            />
          </label>
        )}

        {plan?.format === 'eos' && (
          <label>
            Eos cue list
            <select
              value={list}
              onChange={(e) => {
                setList(e.target.value)
                preview({ list: e.target.value })
              }}
            >
              <option value="">Choose a list…</option>
              {plan.lists.map((l) => (
                <option key={l.number} value={l.number} disabled={!l.cues}>
                  List {l.number}
                  {l.label ? ` · ${l.label}` : ''} · {l.cues} cues
                </option>
              ))}
            </select>
          </label>
        )}

        <div className="row">
          <button className="ghost" onClick={() => preview()} disabled={busy || (!file && !text.trim())}>
            Preview changes
          </button>
          <span className="spacer" />
          <button onClick={confirm} disabled={busy || !plan?.summary || writes === 0}>
            Import
          </button>
        </div>

        {plan?.summary && (
          <>
            <p className="import-summary">
              {ACTIONS.map((a) => (
                <span key={a} className={`chip ${a}`}>
                  {plan.summary[a]} {a === 'reject' ? 'rejected' : a === 'unchanged' ? 'unchanged' : `to ${a}`}
                </span>
              ))}
            </p>
            {changes.length > 0 && (
              <div className="import-table">
                <table>
                  <thead>
                    <tr>
                      <th>Line</th>
                      <th></th>
                      <th>Q</th>
                      <th>Label</th>
                      <th>Detail</th>
                    </tr>
                  </thead>
                  <tbody>
                    {changes.slice(0, 200).map((r, i) => (
                      <tr key={i} className={r.action}>
                        <td>{r.line ?? ''}</td>
                        <td>{r.action}</td>
                        <td>{r.number}</td>
                        <td>{r.label}</td>
                        <td>{r.reason ?? (r.changes?.length ? `changes ${r.changes.join(', ')}` : r.scene)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {changes.length > 200 && <p className="muted small-print">…and {changes.length - 200} more.</p>}
              </div>
            )}
          </>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  )
}
