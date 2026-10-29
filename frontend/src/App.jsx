import { useState } from 'react'
import { getToken, clearToken } from './api'
import Login from './Login'
import Productions from './Productions'
import Board from './Board'

export default function App() {
  const [authed, setAuthed] = useState(Boolean(getToken()))
  const [productionId, setProductionId] = useState(null)

  if (!authed) return <Login onLogin={() => setAuthed(true)} />

  return (
    <div className="shell">
      <header className="topbar">
        <button className="brand" onClick={() => setProductionId(null)}>
          RUN<span>/</span>OF<span>/</span>SHOW
        </button>
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
      {productionId ? (
        <Board productionId={productionId} onBack={() => setProductionId(null)} />
      ) : (
        <Productions onOpen={setProductionId} />
      )}
    </div>
  )
}
