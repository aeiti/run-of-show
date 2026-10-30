import { useState } from 'react'
import { Link } from 'react-router'
import { ApiError, login } from './api'

export default function Login({ onLogin }) {
  // Prefilled with the seed_demo account so the demo opens in one click.
  const [username, setUsername] = useState('demo')
  const [password, setPassword] = useState('curtain-up')
  const [error, setError] = useState('')

  async function submit(e) {
    e.preventDefault()
    setError('')
    try {
      await login(username, password)
      onLogin()
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 400
          ? 'Wrong username or password.'
          : err instanceof ApiError && err.status === 429
            ? 'Too many attempts. Wait a minute and try again.'
            : 'Sign-in failed. Is the backend running and seeded?',
      )
    }
  }

  return (
    <form className="panel login" onSubmit={submit}>
      <h1>
        RUN<span>/</span>OF<span>/</span>SHOW
      </h1>
      <label>
        Username
        <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          autoComplete="current-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      <button type="submit">Sign in</button>
      {error && <p className="error">{error}</p>}
      <p className="auth-links">
        <Link to="/signup">Create an account</Link>
        <Link to="/forgot-password">Forgot password?</Link>
      </p>
    </form>
  )
}
