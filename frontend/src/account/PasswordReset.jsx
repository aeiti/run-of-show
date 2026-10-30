import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api'

export function ForgotPassword() {
  const [email, setEmail] = useState('')
  const [sent, setSent] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await api.requestPasswordReset(email)
      setSent(true)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="panel login" onSubmit={submit}>
      <h2>Reset your password</h2>
      {sent ? (
        // The API answers the same whether or not the address has an account.
        <p className="muted">If an account uses {email}, a reset link is on its way. It works once.</p>
      ) : (
        <>
          <label>
            Email
            <input required autoFocus type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          </label>
          <button type="submit">Send reset link</button>
        </>
      )}
      {error && <p className="error">{error}</p>}
      <p className="auth-links">
        <Link to="/">Back to sign in</Link>
      </p>
    </form>
  )
}

export function ResetPassword() {
  const { uid, token } = useParams()
  const [password, setPassword] = useState('')
  const [done, setDone] = useState(false)
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await api.confirmPasswordReset(uid, token, password)
      setDone(true)
    } catch (err) {
      setError(err.message)
    }
  }

  return (
    <form className="panel login" onSubmit={submit}>
      <h2>Choose a new password</h2>
      {done ? (
        <p className="muted">Password changed. Every device has been signed out.</p>
      ) : (
        <>
          <label>
            New password
            <input
              required
              autoFocus
              type="password"
              autoComplete="new-password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </label>
          <button type="submit">Set password</button>
        </>
      )}
      {error && <p className="error">{error}</p>}
      <p className="auth-links">
        <Link to="/">{done ? 'Sign in' : 'Back to sign in'}</Link>
      </p>
    </form>
  )
}
