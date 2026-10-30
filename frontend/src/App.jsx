import { useEffect, useState } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router'
import { ApiError, api, clearToken, getToken, logout } from './api'
import Login from './Login'
import Productions from './Productions'
import Board from './Board'
import Signup from './account/Signup'
import Profile from './account/Profile'
import Users from './admin/Users'
import { ForgotPassword, ResetPassword } from './account/PasswordReset'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))
  const [me, setMe] = useState(null)

  useEffect(() => {
    if (!authed) return
    api
      .me()
      .then(setMe)
      .catch((err) => {
        // A stale or revoked token (e.g. the password was changed elsewhere).
        if (err instanceof ApiError && err.status === 401) setAuthed(false)
      })
  }, [authed])

  function signedOut() {
    setMe(null)
    setAuthed(false)
  }

  // The server ended this sign-in (signed out elsewhere, password changed, suspended).
  function sessionEnded() {
    clearToken()
    signedOut()
  }

  // The reset link works whether or not someone is signed in on this browser.
  const reset = <Route path="/reset-password/:uid/:token" element={<ResetPassword />} />

  if (!authed) {
    const signedIn = () => setAuthed(true)
    return (
      <Routes>
        <Route path="/signup" element={<Signup onLogin={signedIn} />} />
        <Route path="/forgot-password" element={<ForgotPassword />} />
        {reset}
        <Route path="*" element={<Login onLogin={signedIn} />} />
      </Routes>
    )
  }

  return (
    <div className="shell">
      <header className="topbar">
        <Link className="brand" to="/">
          RUN<span>/</span>OF<span>/</span>SHOW
        </Link>
        <nav className="account-nav">
          {me?.is_admin && (
            <Link className="account-link" to="/users">
              Users
            </Link>
          )}
          {me && (
            <Link className="account-link" to="/profile">
              {me.display_name || me.username}
            </Link>
          )}
          <button className="ghost" onClick={() => logout().finally(signedOut)}>
            Sign out
          </button>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<ProductionsRoute />} />
        <Route path="/profile" element={me ? <Profile me={me} onSaved={setMe} /> : null} />
        <Route path="/users" element={!me ? null : me.is_admin ? <Users me={me} /> : <Navigate to="/" replace />} />
        <Route path="/productions/:productionId" element={<BoardRoute me={me} onSignedOut={sessionEnded} />} />
        <Route
          path="/productions/:productionId/runs/:runId"
          element={<BoardRoute me={me} onSignedOut={sessionEnded} />}
        />
        {reset}
        <Route path="/signup" element={<Navigate to="/" replace />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

function ProductionsRoute() {
  const navigate = useNavigate()
  return <Productions onOpen={(id) => navigate(`/productions/${id}`)} />
}

function BoardRoute({ me, onSignedOut }) {
  const { productionId, runId } = useParams()
  const navigate = useNavigate()
  // Keyed by production only: switching runs keeps the board mounted and animates the change.
  return (
    <Board
      key={productionId}
      productionId={Number(productionId)}
      runId={runId ? Number(runId) : null}
      me={me}
      onSignedOut={onSignedOut}
      onBack={() => navigate('/')}
      onSelectRun={(id, options) => navigate(`/productions/${productionId}/runs/${id}`, options)}
    />
  )
}
