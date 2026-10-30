import { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { follow } from '../live'
import { HoldClock } from '../board/Transport'
import { sortCues } from '../board/state'
import { formatTime } from '../board/cueTime'
import { followSlice, liveRun } from './followView'

/**
 * A view-only board for ASMs and operators on tablets: the cue that is
 * running, the one in standby and what comes after, in type big enough to
 * read at arm's length. It follows the newest run that is still going and
 * moves to a new run when one starts. Anyone who can see the production can
 * open it; nothing here changes the show.
 */
export default function Follow({ productionId, onGone, onSignedOut }) {
  const [production, setProduction] = useState(null)
  const [cues, setCues] = useState(null)
  const [runs, setRuns] = useState(null)
  const [run, setRun] = useState(null)
  const [liveStatus, setLiveStatus] = useState('connecting')
  const [error, setError] = useState('')

  const followed = useMemo(() => (runs ? liveRun(runs) : null), [runs])
  const followedId = followed?.id ?? null
  const cueList = useMemo(() => cues ?? [], [cues])
  const { active, standby, upcoming } = useMemo(() => followSlice(cueList, run?.state), [cueList, run])
  const notesByCue = useMemo(() => Object.groupBy(run?.cue_notes ?? [], (n) => n.cue), [run])
  const hold = run?.state.hold ?? null

  async function loadAll() {
    const [p, c, r] = await Promise.all([api.production(productionId), api.cues(productionId), api.runs(productionId)])
    setProduction(p)
    setCues(sortCues(c))
    setRuns(r)
  }

  useEffect(() => {
    loadAll().catch((e) => setError(e.message))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productionId])

  // Load whichever run is being followed, again whenever that changes. A reply
  // for a run this screen has since moved on from is dropped.
  const following = useRef(followedId)
  following.current = followedId
  const loadRun = useRef(null)
  loadRun.current = async () => {
    if (followedId == null) return setRun(null)
    const r = await api.run(followedId)
    if (following.current === r.id) setRun(r)
  }
  useEffect(() => {
    loadRun.current().catch((e) => setError(e.message))
  }, [followedId])

  // Live updates (frontend/src/live.js), read through a ref so the one socket
  // always sees the latest state.
  const onLive = useRef(null)
  onLive.current = async (message) => {
    try {
      switch (message.type) {
        case 'run.event':
          if (message.run === followedId) setRun((prev) => prev && { ...prev, state: message.state })
          break
        case 'runs':
          // A run started or ended: perhaps a different one to follow.
          setRuns(await api.runs(productionId))
          if (message.run === followedId) await loadRun.current()
          break
        case 'notes':
          if (message.run === followedId) await loadRun.current()
          break
        case 'cues':
          setCues(sortCues(await api.cues(productionId)))
          await loadRun.current()
          break
        case 'production':
        case 'access':
          setProduction(await api.production(productionId))
          break
        case 'production.deleted':
          onGone()
          break
        case 'resync':
          await loadAll()
          await loadRun.current()
          break
      }
      setError('')
    } catch (err) {
      setError(err.message)
    }
  }

  useEffect(
    () =>
      follow(productionId, {
        onMessage: (message) => onLive.current(message),
        onResync: () => onLive.current({ type: 'resync' }),
        onStatus: setLiveStatus,
        onGone,
        onSignedOut,
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [productionId],
  )

  useWakeLock()

  const loading = !production || !cues || !runs
  return (
    <main className={`follow${hold ? ' is-held' : ''}`}>
      <header className="follow-head">
        <Link className="button ghost" to={`/productions/${productionId}`}>
          ← Board
        </Link>
        <div className="follow-title">
          <strong>{production?.name ?? ' '}</strong>
          {run && <span className="muted"> · {run.label}</span>}
        </div>
        <span className={`sync-status ${liveStatus}`} role="status">
          {liveStatus === 'live' ? 'Synced' : liveStatus === 'connecting' ? 'Connecting…' : 'Reconnecting…'}
        </span>
      </header>

      {error && <p className="error">{error}</p>}
      {loading ? (
        <p className="muted">Loading…</p>
      ) : !followed ? (
        <p className="follow-empty">No runs yet. This screen picks up the first one when it starts.</p>
      ) : !run ? (
        <p className="muted">Loading…</p>
      ) : (
        <>
          {hold && (
            <div className="follow-hold" role="status">
              <strong>HOLD</strong> <HoldClock since={hold.since} />
              {hold.reason && <p>{hold.reason}</p>}
            </div>
          )}
          {run.ended_at && <p className="follow-ended">This run has ended.</p>}

          <section className="follow-now" aria-live="polite" aria-label="Running">
            <h2>Running</h2>
            {active ? (
              <FollowCue cue={active} notes={notesByCue[active.id]} />
            ) : (
              <p className="muted">
                {run.state.active_number != null ? `Q${run.state.active_number} (removed)` : 'Not started'}
              </p>
            )}
          </section>

          <section className="follow-standby" aria-label="Standby">
            <h2>Standby</h2>
            {standby ? (
              <FollowCue cue={standby} notes={notesByCue[standby.id]} />
            ) : (
              <p className="muted">End of cue list</p>
            )}
          </section>

          {upcoming.length > 0 && (
            <section className="follow-upcoming" aria-label="Coming up">
              <h2>Coming up</h2>
              <ol>
                {upcoming.map((c) => (
                  <li key={c.id}>
                    <span className="cue-number">Q{c.number}</span>
                    <span className="cue-label">{c.label}</span>
                    <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                  </li>
                ))}
              </ol>
            </section>
          )}
        </>
      )}
    </main>
  )
}

function FollowCue({ cue, notes = [] }) {
  const time = formatTime(cue)
  return (
    <div className="follow-cue">
      <span className="follow-number">Q{cue.number}</span>
      <div className="follow-detail">
        <span className="follow-label">{cue.label || ' '}</span>
        <span className="follow-meta">
          {[cue.scene, cue.page && `p.${cue.page}`, time && `time ${time}`].filter(Boolean).join(' · ')}
        </span>
        {cue.notes && <span className="cue-notes">{cue.notes}</span>}
        {notes.map((n) => (
          <span key={n.id} className="run-note">
            ✎ {n.text}
          </span>
        ))}
      </div>
    </div>
  )
}

/** Keep a tablet's screen on while following, where the browser allows it. */
function useWakeLock() {
  useEffect(() => {
    if (!navigator.wakeLock) return
    let lock = null
    let stopped = false
    const request = async () => {
      if (document.visibilityState !== 'visible') return
      try {
        lock = await navigator.wakeLock.request('screen')
        if (stopped) lock.release()
      } catch {
        // Refused (low battery, or not allowed): the screen just sleeps as usual.
      }
    }
    // The lock is dropped whenever the page is hidden; take it again on return.
    document.addEventListener('visibilitychange', request)
    request()
    return () => {
      stopped = true
      document.removeEventListener('visibilitychange', request)
      lock?.release()
    }
  }, [])
}
