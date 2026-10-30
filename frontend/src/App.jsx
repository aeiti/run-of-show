import { useState } from 'react'
import { Link, Navigate, Route, Routes, useNavigate, useParams } from 'react-router'
import { getToken, clearToken } from './api'
import Login from './Login'
import Productions from './Productions'
import Board from './Board'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))

  if (!authed) return <Login onLogin={() => setAuthed(true)} />

  return (
    <div className="shell">
      <header className="topbar">
        <Link className="brand" to="/">
          RUN<span>/</span>OF<span>/</span>SHOW
        </Link>
        <button
          className="ghost"
          onClick={() => {
            clearToken()
            setAuthed(false)
          }}
        >
          Sign out
        </button>
      </header>
      <Routes>
        <Route path="/" element={<ProductionsRoute />} />
        <Route path="/productions/:productionId" element={<BoardRoute />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </div>
  )
}

function ProductionsRoute() {
  const navigate = useNavigate()
  return <Productions onOpen={(id) => navigate(`/productions/${id}`)} />
}

function BoardRoute() {
  const { productionId } = useParams()
  const navigate = useNavigate()
  // Keyed so switching productions starts a fresh board rather than reusing state.
  return <Board key={productionId} productionId={Number(productionId)} onBack={() => navigate('/')} />
}
