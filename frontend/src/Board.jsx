import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './api'
import CueEditor from './board/CueEditor'
import ProductionHeader from './board/ProductionHeader'
import RunPanel from './board/RunPanel'
import Transport from './board/Transport'
import { cueStates, findByNumber, playheadIndex, sortCues, stepLoad } from './board/state'

gsap.registerPlugin(useGSAP)

// GSAP owns each card's look (on .cue-inner); React only renders content.
// The entrance animates the outer <li>, so the two never tween the same property.
const STANDBY = { backgroundColor: '#22262d', borderColor: '#8a929e', opacity: 1, scale: 1 }
const LOOK = {
  pending: { backgroundColor: '#14171c', borderColor: '#262b33', opacity: 0.7, scale: 1 },
  standby: STANDBY,
  loaded: STANDBY,
  active: { backgroundColor: '#3a2d0a', borderColor: '#e8b730', opacity: 1, scale: 1.02 },
  complete: { backgroundColor: '#101216', borderColor: '#1d2026', opacity: 0.4, scale: 1 },
}

const FLASH = {
  from: { boxShadow: '0 0 0 8px rgba(232, 183, 48, 0.55)' },
  to: { boxShadow: '0 0 0 0px rgba(232, 183, 48, 0)', duration: 0.6, ease: 'power2.out' },
}

const STATUS = { complete: 'DONE', active: 'GO', loaded: 'LOAD', standby: 'STBY', pending: '' }

// Preview runs through the list from the top: cue i active, i+1 standby.
function previewState(i, activeIdx) {
  if (i < activeIdx) return 'complete'
  if (i === activeIdx) return 'active'
  if (i === activeIdx + 1) return 'standby'
  return 'pending'
}

// Playhead sits over the centre of cue i on the track; -1 is "before the top of show".
const playheadPos = (i, n) => (i < 0 || n === 0 ? '0%' : `${((i + 0.5) / n) * 100}%`)

export default function Board({ productionId, runId, onBack, onSelectRun }) {
  const [production, setProduction] = useState(null)
  const [cues, setCues] = useState(null)
  const [runs, setRuns] = useState([])
  const [run, setRun] = useState(null)
  const [loadedCue, setLoadedCue] = useState(null)
  const [gotoText, setGotoText] = useState('')
  const [mode, setMode] = useState('live')
  const [busy, setBusy] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [error, setError] = useState('')

  const scope = useRef(null)
  const cardRefs = useRef([])
  const markerRef = useRef(null)
  const fillRef = useRef(null)
  const previewTl = useRef(null)
  const gotoRef = useRef(null)

  const cueList = useMemo(() => cues ?? [], [cues])
  const loaded = Boolean(production && cues && run)
  const live = mode === 'live'
  const ended = Boolean(run?.ended_at)

  // The server decides the active and next cue; the board looks them up and
  // overlays the operator's loaded cue, which only exists on this screen.
  const states = useMemo(() => cueStates(cueList, run?.state, loadedCue), [cueList, run, loadedCue])
  const playIdx = useMemo(() => playheadIndex(cueList, run?.state), [cueList, run])
  const nextCue = cueList.find((c) => c.id === (loadedCue ?? run?.state.next_cue))
  const gotoTarget = findByNumber(cueList, gotoText)
  const canBack =
    run?.state.active_number != null && cueList.some((c) => Number(c.number) < Number(run.state.active_number))

  useEffect(() => {
    let cancelled = false
    Promise.all([api.production(productionId), api.cues(productionId), api.runs(productionId)])
      .then(async ([p, c, r]) => {
        if (cancelled) return
        setProduction(p)
        setCues(c)
        setRuns(r)
        // No run in the URL: open the latest one, or start "Run 1".
        if (!runId) {
          const target = r[0] ?? (await api.createRun(productionId, { label: 'Run 1' }))
          if (!r.length) setRuns([target])
          onSelectRun(target.id, { replace: true })
        }
      })
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
    // Only on a new production: runId changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productionId])

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    api
      .run(runId)
      .then((r) => {
        if (cancelled) return
        if (r.production !== productionId) throw new Error('That run belongs to another production.')
        setRun(r)
        setLoadedCue(null)
      })
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [runId, productionId])

  // Typing in GOTO follows whatever cue is loaded.
  useEffect(() => {
    const cue = cueList.find((c) => c.id === loadedCue)
    if (cue) setGotoText(cue.number)
  }, [loadedCue, cueList])

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
      cardRefs.current.length = cueList.length
      applyStates(states, playIdx, 0)
      gsap.from('.track', { scaleX: 0, transformOrigin: 'left center', duration: 0.6, ease: 'power3.out' })
      gsap.from('.cue-list > li', { y: 28, autoAlpha: 0, duration: 0.5, ease: 'power3.out', stagger: 0.05 })
    },
    { dependencies: [loaded, live], scope },
  )

  // Settle the cards whenever the run state, the loaded cue or the cue list changes.
  useEffect(() => {
    if (loaded && live && !previewing) applyStates(states, playIdx, 0.4)
  }, [loaded, live, previewing, states, playIdx, applyStates])

  // GO, BACK, GOTO and RESET all append one event and return the new state.
  const act = contextSafe(async (action, cueId) => {
    if (!live || busy || previewing || !run || ended) return
    if (action === 'go' && !nextCue) return
    setBusy(true)
    setError('')
    try {
      const target = action === 'go' ? (loadedCue ?? undefined) : cueId
      const { event, state } = await api[action](run.id, target)
      setRun((prev) => ({ ...prev, events: [...prev.events, event], state }))
      setLoadedCue(null)
      // The settle effect tweens the states; this adds the flash on top.
      const card = cardRefs.current[cueList.findIndex((c) => c.id === state.active_cue)]
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

  // Clicking a card loads it (clicking again unloads). It never fires.
  function toggleLoad(cueId) {
    if (previewing || ended) return
    setLoadedCue((current) => (current === cueId ? null : cueId))
  }

  // Preview: a visual-only timeline through every cue. Nothing is POSTed.
  const preview = contextSafe(() => {
    if (previewing || cueList.length === 0) return
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

  async function createRun(data) {
    try {
      const created = await api.createRun(productionId, data)
      setRuns((prev) => [created, ...prev])
      onSelectRun(created.id)
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  async function endRun() {
    try {
      const updated = await api.endRun(run.id)
      setRun((prev) => ({ ...prev, ...updated }))
      setRuns((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
      setLoadedCue(null)
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

  // Desk-style keys. Ignored while typing, except Esc.
  useEffect(() => {
    const onKey = (e) => {
      if (!live) return
      const typing = e.target.closest('input, textarea, select')
      if (e.key === 'Escape') {
        setLoadedCue(null)
        if (typing) e.target.blur()
        return
      }
      if (typing || e.metaKey || e.ctrlKey || e.altKey) return
      // Space is always GO, even with a button focused (that would otherwise click it).
      if (e.code === 'Space') {
        e.preventDefault()
        act('go')
      } else if (e.key === 'b' || e.key === 'ArrowLeft') {
        act('back')
      } else if (e.key === 'g') {
        e.preventDefault()
        gotoRef.current?.focus()
        gotoRef.current?.select()
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        if (!ended) setLoadedCue(stepLoad(cueList, run?.state, loadedCue, e.key === 'ArrowDown' ? 1 : -1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [live, act, cueList, run, loadedCue, ended])

  const goLabel = ended ? 'ENDED' : nextCue || cueList.length === 0 ? 'GO' : 'END'
  const nextText = nextCue
    ? `${loadedCue ? 'Loaded' : 'Next'}: Q${nextCue.number} ${nextCue.label}`
    : 'End of cue list'

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
        {cueList.map((c, i) => (
          <span key={c.id} className="tick" style={{ left: playheadPos(i, cueList.length) }}>
            {c.number}
          </span>
        ))}
        <div className="playhead" ref={markerRef} />
      </div>

      <div className="board-body">
        {live ? (
          <ol className="cue-list">
            {cueList.map((c, i) => [
              c.scene && (
                <li key={`scene-${c.id}`} className="scene-divider">
                  {c.scene}
                </li>
              ),
              <li key={c.id} className="cue-card">
                <button
                  type="button"
                  className="cue-inner"
                  ref={(el) => (cardRefs.current[i] = el)}
                  aria-pressed={c.id === loadedCue}
                  aria-label={`Load Q${c.number} ${c.label}`}
                  onClick={() => toggleLoad(c.id)}
                >
                  <span className="cue-number">Q{c.number}</span>
                  <span className="cue-label">
                    {c.label}
                    {c.notes && <small className="cue-notes">{c.notes}</small>}
                  </span>
                  <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                  <span className="cue-status">{STATUS[states[i]]}</span>
                </button>
              </li>,
            ])}
            {cues && cues.length === 0 && <li className="muted">No cues yet. Switch to Edit to add some.</li>}
          </ol>
        ) : (
          <CueEditor
            cues={cueList}
            productionId={productionId}
            onSaved={(saved) => afterCueChange(cueList.map((c) => (c.id === saved.id ? saved : c)))}
            onCreated={(created) => afterCueChange([...cueList, created])}
            onDeleted={(id) => afterCueChange(cueList.filter((c) => c.id !== id))}
          />
        )}

        <aside className="controls">
          {live ? (
            <>
              {previewing && <p className="preview-banner">PREVIEW · not recorded</p>}
              <Transport
                disabled={busy || previewing || !run || ended}
                goLabel={goLabel}
                canGo={Boolean(nextCue)}
                canBack={canBack}
                nextText={nextText}
                gotoText={gotoText}
                onGotoText={setGotoText}
                gotoTarget={gotoTarget}
                gotoRef={gotoRef}
                onAction={act}
              />
              {previewing ? (
                <button className="ghost wide" onClick={stopPreview}>
                  Stop preview
                </button>
              ) : (
                <button className="ghost wide" onClick={preview} disabled={cueList.length === 0}>
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

          <RunPanel runs={runs} run={run} onSelect={onSelectRun} onCreate={createRun} onEnd={endRun} />
          {error && <p className="error">{error}</p>}
        </aside>
      </div>
    </main>
  )
}
