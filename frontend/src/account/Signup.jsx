import { useState } from 'react'
import { Link } from 'react-router'
import { signup } from '../api'

const blank = { username: '', email: '', display_name: '', password: '' }

export default function Signup({ onLogin }) {
  const [form, setForm] = useState(blank)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await signup(form)
      onLogin()
    } catch (err) {
      setError(err.message)
    }
  }

  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) })

  return (
    <form className="panel login" onSubmit={submit}>
      <h1>
        RUN<span>/</span>OF<span>/</span>SHOW
      </h1>
      <label>
        Username
        <input required autoFocus autoComplete="username" {...field('username')} />
      </label>
      <label>
        Email
        <input required type="email" autoComplete="email" {...field('email')} />
      </label>
      <label>
        <span>
          Display name <span className="hint">optional</span>
        </span>
        <input autoComplete="name" {...field('display_name')} />
      </label>
      <label>
        Password
        <input required type="password" autoComplete="new-password" {...field('password')} />
      </label>
      <button type="submit">Create account</button>
      {error && <p className="error">{error}</p>}
      <p className="auth-links">
        <Link to="/">Already have an account? Sign in</Link>
      </p>
    </form>
  )
}
