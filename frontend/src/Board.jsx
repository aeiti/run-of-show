import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './api'
import CueEditor from './board/CueEditor'
import ProductionHeader from './board/ProductionHeader'
import { cueStates, playheadIndex, sortCues } from './board/state'

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

const STATUS = { complete: 'DONE', active: 'GO', standby: 'STBY', pending: '' }

// Preview runs through the list from the top: cue i active, i+1 standby.
function previewState(i, activeIdx) {
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
  const [mode, setMode] = useState('live')
  const [loaded, setLoaded] = useState(false)
  const [busy, setBusy] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState('')

  const scope = useRef(null)
  const cardRefs = useRef([])
  const markerRef = useRef(null)
  const fillRef = useRef(null)
  const previewTl = useRef(null)

  // The server decides the active and next cue; the board just looks them up.
  const events = run?.events ?? []
  const states = useMemo(() => cueStates(cues, run?.state), [cues, run])
  const playIdx = useMemo(() => playheadIndex(cues, run?.state), [cues, run])
  const nextCue = cues.find((c) => c.id === run?.state.next_cue)
  const live = mode === 'live'

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

  const applyStates = useCallback((looks, idx, duration) => {
    const n = looks.length
    cardRefs.current.forEach((card, i) => {
      if (card && looks[i]) gsap.to(card, { ...LOOK[looks[i]], duration, ease: 'power2.out' })
    })
    gsap.to(markerRef.current, { left: playheadPos(idx, n), duration, ease: 'power3.inOut' })
    gsap.to(fillRef.current, { width: playheadPos(idx, n), duration, ease: 'power3.inOut' })
  }, [])

  // Entrance, on first load and whenever the board returns to Live mode:
  // set every card to its state for the current run, then stagger them in.
  useGSAP(
    () => {
      if (!loaded || !live) return
      cardRefs.current.length = cues.length
      applyStates(states, playIdx, 0)
      gsap.from('.track', { scaleX: 0, transformOrigin: 'left center', duration: 0.6, ease: 'power3.out' })
      gsap.from('.cue-list > li', { y: 28, autoAlpha: 0, duration: 0.5, ease: 'power3.out', stagger: 0.05 })
    },
    { dependencies: [loaded, live], scope },
  )

  // Settle the cards whenever the run state or the cue list changes.
  useEffect(() => {
    if (loaded && live && !previewing) applyStates(states, playIdx, 0.4)
  }, [loaded, live, previewing, states, playIdx, applyStates])

  const go = contextSafe(async () => {
    if (!live || busy || previewing || !nextCue) return
    setBusy(true)
    setError('')
    try {
      const { event, state } = await api.go(run.id)
      setRun((prev) => ({ ...prev, events: [...prev.events, event], state }))
      // The settle effect tweens the states; this adds the GO flash on top.
      const card = cardRefs.current[cues.findIndex((c) => c.id === state.active_cue)]
      if (card) {
        gsap.fromTo(card, FLASH.from, FLASH.to)
        card.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
      }
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
    cards.forEach((card, i) => tl.set(card, LOOK[previewState(i, -1)], 0))
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

  // Any cue edit can change which cue is next, so refresh the run state after it.
  async function afterCueChange(nextCues) {
    setCues(sortCues(nextCues))
    try {
      setRun(await api.run(run.id))
    } catch (err) {
      setError(err.message)
    }
  }

  // Space bar is GO, like the button on a lighting desk.
  useEffect(() => {
    const onKey = (e) => {
      if (e.code !== 'Space' || e.target.closest('input, textarea, button')) return
      e.preventDefault()
      go()
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [go])

  return (
    <main className={`board ${previewing ? 'is-previewing' : ''}`} ref={scope}>
      <div className="board-head">
        <button className="ghost" onClick={onBack}>
          ← Productions
        </button>
        <ProductionHeader production={production} onSaved={setProduction} onDeleted={onBack} />
        <div className="mode-toggle" role="group" aria-label="Board mode">
          <button className={live ? 'on' : ''} aria-pressed={live} onClick={() => setMode('live')}>
            Live
          </button>
          <button
            className={live ? '' : 'on'}
            aria-pressed={!live}
            disabled={previewing}
            onClick={() => setMode('edit')}
          >
            Edit
          </button>
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
        {live ? (
          <ol className="cue-list">
            {cues.map((c, i) => [
              c.scene && (
                <li key={`scene-${c.id}`} className="scene-divider">
                  {c.scene}
                </li>
              ),
              <li key={c.id} className="cue-card">
                <div className="cue-inner" ref={(el) => (cardRefs.current[i] = el)}>
                  <span className="cue-number">Q{c.number}</span>
                  <span className="cue-label">
                    {c.label}
                    {c.notes && <small className="cue-notes">{c.notes}</small>}
                  </span>
                  <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                  <span className="cue-status">{STATUS[states[i]]}</span>
                </div>
              </li>,
            ])}
            {loaded && cues.length === 0 && <li className="muted">No cues yet. Switch to Edit to add some.</li>}
          </ol>
        ) : (
          <CueEditor
            cues={cues}
            productionId={productionId}
            onSaved={(saved) => afterCueChange(cues.map((c) => (c.id === saved.id ? saved : c)))}
            onCreated={(created) => afterCueChange([...cues, created])}
            onDeleted={(id) => afterCueChange(cues.filter((c) => c.id !== id))}
          />
        )}

        <aside className="controls">
          {live ? (
            <>
              {previewing && <p className="preview-banner">PREVIEW · not recorded</p>}
              <button className="go" onClick={go} disabled={busy || previewing || !nextCue}>
                {nextCue || cues.length === 0 ? 'GO' : 'END'}
              </button>
              <p className="muted next">{nextCue ? `Next: Q${nextCue.number} ${nextCue.label}` : 'End of cue list'}</p>

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
            </>
          ) : (
            <p className="muted edit-help">
              Editing the cue list. Enter or leaving a field saves it; Esc puts it back. The list stays in cue-number
              order. Switch back to Live to run the show.
            </p>
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
          {error && <p className="error">{error}</p>}
        </aside>
      </div>
    </main>
  )
}
