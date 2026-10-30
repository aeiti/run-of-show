import { useEffect, useState } from 'react'
import { api } from './api'

const blank = { name: '', company: '', venue: '', performance_date: '' }

export default function Productions({ onOpen }) {
  const [productions, setProductions] = useState([])
  const [form, setForm] = useState(blank)
  const [error, setError] = useState('')

  useEffect(() => {
    api.productions().then(setProductions).catch((e) => setError(e.message))
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
              <button onClick={() => onOpen(p.id)}>
                <strong>{p.name}</strong>
                <span className="muted">
                  {[p.company, p.venue, p.performance_date].filter(Boolean).join(' · ')}
                </span>
              </button>
            </li>
          ))}
        </ul>
      </section>
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
    </main>
  )
}
