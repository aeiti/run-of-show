import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { flushSync } from 'react-dom'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './api'

gsap.registerPlugin(useGSAP)

// GSAP owns each card's look (on .cue-inner); React only renders content.
// The entrance animates the outer <li>, so the two never tween the same property.
const LOOK = {
  pending: { backgroundColor: '#14171c', borderColor: '#262b33', opacity: 0.7, scale: 1 },
  standby: { backgroundColor: '#22262d', borderColor: '#8a929e', opacity: 1, scale: 1 },
  active: { backgroundColor: '#3a2d0a', borderColor: '#e8b730', opacity: 1, scale: 1.02 },
  complete: { backgroundColor: '#101216', borderColor: '#1d2026', opacity: 0.4, scale: 1 },
}

const FLASH = {
  from: { boxShadow: '0 0 0 8px rgba(232, 183, 48, 0.55)' },
  to: { boxShadow: '0 0 0 0px rgba(232, 183, 48, 0)', duration: 0.6, ease: 'power2.out' },
}

function stateAt(i, activeIdx) {
  if (i < activeIdx) return 'complete'
  if (i === activeIdx) return 'active'
  if (i === activeIdx + 1) return 'standby'
  return 'pending'
}

// Playhead sits over the centre of cue i on the track; -1 is "before the top of show".
const playheadPos = (i, n) => (i < 0 || n === 0 ? '0%' : `${((i + 0.5) / n) * 100}%`)

export default function Board({ productionId, onBack }) {
  const [production, setProduction] = useState(null)
  const [cues, setCues] = useState([])
  const [run, setRun] = useState(null)
  const [runDraft, setRunDraft] = useState('Run 1')
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [newCue, setNewCue] = useState({ number: '', label: '', page: '' })
  const [error, setError] = useState('')

  const scope = useRef(null)
  const cardRefs = useRef([])
  const markerRef = useRef(null)
  const fillRef = useRef(null)
  const previewTl = useRef(null)

  // The server decides the active and next cue; the board just finds them.
  const events = run?.events ?? []
  const activeIdx = useMemo(
    () => cues.findIndex((c) => c.id === run?.state.active_cue),
    [cues, run],
  )
  const nextIdx = useMemo(() => cues.findIndex((c) => c.id === run?.state.next_cue), [cues, run])
  const done = cues.length > 0 && nextIdx === -1

  // Open a run by label, creating it if this production doesn't have one yet.
  const openRun = useCallback(
    async (label) => {
      const runs = await api.runs(productionId)
      const found = runs.find((r) => r.label === label) ?? (await api.createRun(productionId, { label }))
      setRun(await api.run(found.id))
    },
    [productionId],
  )

  useEffect(() => {
    Promise.all([api.production(productionId), api.cues(productionId), openRun('Run 1')])
      .then(([p, c]) => {
        setProduction(p)
        setCues(c)
        setLoaded(true)
      })
      .catch((e) => setError(e.message))
  }, [productionId, openRun])

  const { contextSafe } = useGSAP({ scope })

  const applyStates = useCallback(
    (idx, duration) => {
      const n = cardRefs.current.length
      cardRefs.current.forEach((card, i) => {
        if (card) gsap.to(card, { ...LOOK[stateAt(i, idx)], duration, ease: 'power2.out' })
      })
      gsap.to(markerRef.current, { left: playheadPos(idx, n), duration, ease: 'power3.inOut' })
      gsap.to(fillRef.current, { width: playheadPos(idx, n), duration, ease: 'power3.inOut' })
    },
    [],
  )

  // Entrance: set every card to its state for the current run, then stagger them in.
  useGSAP(
    () => {
      if (!loaded) return
      cardRefs.current.length = cues.length
      applyStates(activeIdx, 0)
      gsap.from('.track', { scaleX: 0, transformOrigin: 'left center', duration: 0.6, ease: 'power3.out' })
      gsap.from('.cue-card', { y: 28, autoAlpha: 0, duration: 0.5, ease: 'power3.out', stagger: 0.06 })
    },
    { dependencies: [loaded], scope },
  )

  const go = contextSafe(async () => {
    if (busy || previewing || done || cues.length === 0) return
    setBusy(true)
    setError('')
    try {
      const { event, state } = await api.go(run.id)
      setRun((prev) => ({ ...prev, events: [...prev.events, event], state }))
      // The settle effect below tweens the states; this adds the GO flash on top.
      const card = cardRefs.current[cues.findIndex((c) => c.id === state.active_cue)]
      gsap.fromTo(card, FLASH.from, FLASH.to)
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    } catch (e) {
      setError(e.message)
    } finally {
      setBusy(false)
    }
  })

  // Preview: a visual-only timeline through every cue. Nothing is POSTed.
  const preview = contextSafe(() => {
    if (previewing || cues.length === 0) return
    const cards = cardRefs.current
    const n = cards.length
    setPreviewing(true)
    const tl = gsap.timeline({
      defaults: { duration: 0.35, ease: 'power2.out' },
      onComplete: () => stopPreview(),
    })
    cards.forEach((card, i) => tl.set(card, LOOK[stateAt(i, -1)], 0))
    tl.set(markerRef.current, { left: '0%' }, 0)
    tl.set(fillRef.current, { width: '0%' }, 0)
    cards.forEach((card, i) => {
      tl.addLabel(`q${i}`, '+=0.45')
      tl.to(card, LOOK.active, `q${i}`)
      // immediateRender: false, or every card would show its flash start state at t=0.
      tl.fromTo(card, FLASH.from, { ...FLASH.to, immediateRender: false }, `q${i}`)
      if (i > 0) tl.to(cards[i - 1], LOOK.complete, `q${i}`)
      if (i + 1 < n) tl.to(cards[i + 1], LOOK.standby, `q${i}`)
      tl.to(markerRef.current, { left: playheadPos(i, n), ease: 'power3.inOut' }, `q${i}`)
      tl.to(fillRef.current, { width: playheadPos(i, n), ease: 'power3.inOut' }, `q${i}`)
    })
    tl.to({}, { duration: 0.8 })
    previewTl.current = tl
  })

  const stopPreview = contextSafe(() => {
    previewTl.current?.kill()
    previewTl.current = null
    setPreviewing(false)
  })

  // When preview ends (or the run changes), settle the board back to the recorded run.
  useEffect(() => {
    if (loaded && !previewing) applyStates(activeIdx, 0.4)
  }, [loaded, previewing, activeIdx, cues, applyStates])

  async function loadRun(e) {
    e.preventDefault()
    const label = runDraft.trim()
    if (!label || label === run?.label) return
    try {
      await openRun(label)
    } catch (err) {
      setError(err.message)
    }
  }

  const addCue = contextSafe(async (e) => {
    e.preventDefault()
    try {
      const created = await api.createCue(productionId, {
        number: newCue.number,
        label: newCue.label,
        page: newCue.page ? Number(newCue.page) : null,
      })
      // Cues are ordered by number, so a new cue can land anywhere in the list.
      const sorted = [...cues, created].sort((a, b) => Number(a.number) - Number(b.number))
      flushSync(() => setCues(sorted))
      cardRefs.current.length = sorted.length
      const i = sorted.indexOf(created)
      gsap.from(cardRefs.current[i].parentElement, { y: 16, autoAlpha: 0, duration: 0.4, ease: 'power3.out' })
      setNewCue({ number: '', label: '', page: '' })
      // The next cue may have changed; refresh the run's state from the server.
      setRun(await api.run(run.id))
    } catch (err) {
      setError(err.message)
    }
  })

  // Space bar is GO, like the button on a lighting desk.
  useEffect(() => {
    const onKey = (e) => {
      if (e.code !== 'Space' || e.target.closest('input, button')) return
      e.preventDefault()
      go()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go])

  const status = (i) => ({ complete: 'DONE', active: 'GO', standby: 'STBY', pending: '' })[stateAt(i, activeIdx)]

  return (
    <main className={`board ${previewing ? 'is-previewing' : ''}`} ref={scope}>
      <div className="board-head">
        <button className="ghost" onClick={onBack}>
          ← Productions
        </button>
        <div>
          <h2>{production?.name ?? '…'}</h2>
          <p className="muted">
            {[production?.venue, production?.performance_date].filter(Boolean).join(' · ')}
          </p>
        </div>
      </div>

      <div className="track" aria-hidden="true">
        <div className="track-fill" ref={fillRef} />
        {cues.map((c, i) => (
          <span key={c.id} className="tick" style={{ left: playheadPos(i, cues.length) }}>
            {c.number}
          </span>
        ))}
        <div className="playhead" ref={markerRef} />
      </div>

      <div className="board-body">
        <ol className="cue-list">
          {cues.map((c, i) => (
            <li key={c.id} className="cue-card">
              <div className="cue-inner" ref={(el) => (cardRefs.current[i] = el)}>
                <span className="cue-number">Q{c.number}</span>
                <span className="cue-label">{c.label}</span>
                <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                <span className="cue-status">{status(i)}</span>
              </div>
            </li>
          ))}
          {loaded && cues.length === 0 && <li className="muted">No cues yet. Add one below.</li>}
        </ol>

        <aside className="controls">
          {previewing && <p className="preview-banner">PREVIEW · not recorded</p>}
          <button className="go" onClick={go} disabled={busy || previewing || done || cues.length === 0}>
            {done ? 'END' : 'GO'}
          </button>
          <p className="muted next">
            {cues[nextIdx] ? `Next: Q${cues[nextIdx].number} ${cues[nextIdx].label}` : 'End of cue list'}
          </p>

          <form className="row" onSubmit={loadRun}>
            <input value={runDraft} onChange={(e) => setRunDraft(e.target.value)} aria-label="Run label" />
            <button type="submit" className="ghost">
              Load run
            </button>
          </form>

          {previewing ? (
            <button className="ghost" onClick={stopPreview}>
              Stop preview
            </button>
          ) : (
            <button className="ghost" onClick={preview} disabled={cues.length === 0}>
              Preview run
            </button>
          )}

          <h3>Run log · {run?.label}</h3>
          <ol className="log">
            {events.length === 0 && <li className="muted">No cues fired in this run.</li>}
            {events.map((e) => (
              <li key={e.id}>
                <time>{new Date(e.fired_at).toLocaleTimeString()}</time>
                {e.action !== 'go' && <b className="log-action">{e.action.toUpperCase()} </b>}
                {e.action !== 'reset' && `Q${e.cue_number} ${e.cue_label}`}
              </li>
            ))}
          </ol>

          <form className="add-cue" onSubmit={addCue}>
            <h3>Add cue</h3>
            <div className="row">
              <input
                required
                placeholder="#"
                className="narrow"
                value={newCue.number}
                onChange={(e) => setNewCue({ ...newCue, number: e.target.value })}
              />
              <input
                placeholder="Label"
                value={newCue.label}
                onChange={(e) => setNewCue({ ...newCue, label: e.target.value })}
              />
              <input
                placeholder="pg"
                className="narrow"
                inputMode="numeric"
                value={newCue.page}
                onChange={(e) => setNewCue({ ...newCue, page: e.target.value })}
              />
              <button type="submit" className="ghost">
                Add
              </button>
            </div>
          </form>
          {error && <p className="error">{error}</p>}
        </aside>
      </div>
    </main>
  )
}
