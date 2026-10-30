import { useState } from 'react'
import { api, changePassword } from '../api'

export default function Profile({ me, onSaved }) {
  return (
    <main className="profile">
      <Details me={me} onSaved={onSaved} />
      <Password />
    </main>
  )
}

function Details({ me, onSaved }) {
  const [form, setForm] = useState({ display_name: me.display_name, email: me.email ?? '' })
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  async function save(e) {
    e.preventDefault()
    setError('')
    try {
      onSaved(await api.updateMe(form))
      setStatus('Saved.')
    } catch (err) {
      setStatus('')
      setError(err.message)
    }
  }

  const field = (key) => ({
    value: form[key],
    onChange: (e) => {
      setStatus('')
      setForm({ ...form, [key]: e.target.value })
    },
  })

  return (
    <form className="panel" onSubmit={save}>
      <h2>Profile</h2>
      <p className="muted profile-username">Signed in as {me.username}</p>
      <label>
        Display name
        <input autoComplete="name" {...field('display_name')} />
      </label>
      <label>
        Email
        <input type="email" autoComplete="email" {...field('email')} />
      </label>
      <button type="submit">Save</button>
      {status && <p className="ok">{status}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  )
}

function Password() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  async function save(e) {
    e.preventDefault()
    setError('')
    setStatus('')
    try {
      await changePassword(current, next)
      setCurrent('')
      setNext('')
      setStatus('Password changed. Other devices have been signed out.')
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="panel" onSubmit={save}>
      <h2>Change password</h2>
      <label>
        Current password
        <input
          required
          type="password"
          autoComplete="current-password"
          value={current}
          onChange={(e) => setCurrent(e.target.value)}
        />
      </label>
      <label>
        New password
        <input required type="password" autoComplete="new-password" value={next} onChange={(e) => setNext(e.target.value)} />
      </label>
      <button type="submit">Change password</button>
      {status && <p className="ok">{status}</p>}
      {error && <p className="error">{error}</p>}
    </form>
  )
}
