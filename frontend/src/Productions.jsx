import { useEffect, useState } from 'react'
import { api } from './api'
import { ROLES } from './access'
import ProductionLogo from './ProductionLogo'

const blank = { name: '', company: '', venue: '', performance_date: '' }

export default function Productions({ onOpen }) {
  const [productions, setProductions] = useState([])
  const [form, setForm] = useState(blank)
  const [error, setError] = useState('')
  const [listError, setListError] = useState('')
  const [importError, setImportError] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api.productions().then(setProductions).catch((e) => setListError(e.message))
  }, [])

  async function create(e) {
    e.preventDefault()
    try {
      const created = await api.createProduction({
        ...form,
        performance_date: form.performance_date || null,
      })
      setProductions([created, ...productions])
      setForm(blank)
    } catch (e) {
      setError(e.message)
    }
  }

  // Runs and actions on one production; the copy or import goes to the top of the list.
  async function act(fn, setErr) {
    setBusy(true)
    setErr('')
    try {
      const added = await fn()
      if (added) setProductions((list) => [added, ...list])
    } catch (e) {
      setErr(e.message)
    } finally {
      setBusy(false)
    }
  }

  function importFile(e) {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    act(() => api.importProduction(form), setImportError)
  }

  const field = (key) => ({
    value: form[key],
    onChange: (e) => setForm({ ...form, [key]: e.target.value }),
  })

  return (
    <main className="productions">
      <section className="panel">
        <h2>Productions</h2>
        {productions.length === 0 && <p className="muted">No productions yet.</p>}
        <ul className="production-list">
          {productions.map((p) => (
            <li key={p.id}>
              <button className="production-open" onClick={() => onOpen(p.id)}>
                <span className="production-title">
                  <ProductionLogo production={p} />
                  <strong>{p.name}</strong>
                </span>
                <span className="muted">
                  {[p.company, p.venue, p.performance_date].filter(Boolean).join(' · ')}
                  {p.role !== 'owner' && (
                    <span className="shared-badge">
                      {ROLES[p.role]} · {p.owner.display_name || p.owner.username}
                    </span>
                  )}
                </span>
              </button>
              <button
                className="ghost small"
                disabled={busy}
                title="Copy the details and cue list, without runs"
                onClick={() => act(() => api.duplicateProduction(p.id), setListError)}
              >
                Duplicate
              </button>
              <button
                className="ghost small"
                disabled={busy}
                title="Download the details, cues, runs and logs as JSON"
                onClick={() => act(() => api.exportProduction(p.id), setListError)}
              >
                Export
              </button>
            </li>
          ))}
        </ul>
        {listError && <p className="error">{listError}</p>}
      </section>
      <div className="side">
        <form className="panel" onSubmit={create}>
          <h2>New production</h2>
          <label>
            Name
            <input required {...field('name')} />
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
            Performance date
            <input type="date" {...field('performance_date')} />
          </label>
          <button type="submit">Create</button>
          {error && <p className="error">{error}</p>}
        </form>
        <section className="panel">
          <h2>Import production</h2>
          <label>
            A production exported as JSON. It is added as a new production.
            <input type="file" accept=".json,application/json" disabled={busy} onChange={importFile} />
          </label>
          {importError && <p className="error">{importError}</p>}
        </section>
      </div>
    </main>
  )
}
