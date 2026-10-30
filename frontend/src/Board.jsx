import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './api'
import CueEditor from './board/CueEditor'
import ImportDialog from './board/ImportDialog'
import ProductionHeader from './board/ProductionHeader'
import Playback from './board/Playback'
import RunPanel from './board/RunPanel'
import Transport from './board/Transport'
import { extraTotal, fadeFor, formatSeconds, formatTime } from './board/cueTime'
import { FLASH, LOOK, STATUS, playheadPos } from './board/looks'
import { cueStates, findByNumber, playheadIndex, sortCues, stepLoad } from './board/state'

gsap.registerPlugin(useGSAP)
// The fade bars are timers: after a stalled frame they should jump to where
// real time says they are, not resume slowly as GSAP does by default.
gsap.ticker.lagSmoothing(0)

// GSAP owns each card's look (on .cue-inner); React only renders content.
// The entrance animates the outer <li>, so the two never tween the same property.
// Each card's .cue-fade bar fills over the cue's time after it goes, so the
// operator can see when a cue has finished; a later action cuts it off.

export default function Board({ productionId, runId, onBack, onSelectRun }) {
  const [production, setProduction] = useState(null)
  const [cues, setCues] = useState(null)
  const [runs, setRuns] = useState([])
  const [run, setRun] = useState(null)
  const [loadedCue, setLoadedCue] = useState(null)
  const [gotoText, setGotoText] = useState('')
  const [mode, setMode] = useState('live')
  const [busy, setBusy] = useState(false)
  const [playingBack, setPlayingBack] = useState(false)
  const [error, setError] = useState('')
  const [importing, setImporting] = useState(false)

  const scope = useRef(null)
  const cardRefs = useRef([])
  const markerRef = useRef(null)
  const fillRef = useRef(null)
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
        setPlayingBack(false)
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
      if (!card || !looks[i]) return
      gsap.to(card, { ...LOOK[looks[i]], duration, ease: 'power2.out' })
      const bar = card.querySelector('.cue-fade')
      if (looks[i] !== 'active') {
        gsap.killTweensOf(bar)
        gsap.set(bar, { scaleX: 0 })
      } else if (!gsap.isTweening(bar)) {
        gsap.set(bar, { scaleX: 1 }) // already active when the board opened: its fade is long over
      }
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
      // A real show has hundreds of cues: keep the whole entrance under a second.
      const each = Math.min(0.05, 1 / cueList.length)
      gsap.from('.cue-list > li', { y: 28, autoAlpha: 0, duration: 0.5, ease: 'power3.out', stagger: each })
    },
    { dependencies: [loaded, live], scope },
  )

  // Settle the cards whenever the run state, the loaded cue or the cue list changes.
  useEffect(() => {
    if (loaded && live && !playingBack) applyStates(states, playIdx, 0.4)
  }, [loaded, live, playingBack, states, playIdx, applyStates])

  // GO, BACK, GOTO and RESET all append one event and return the new state.
  const act = contextSafe(async (action, cueId) => {
    if (!live || busy || playingBack || !run || ended) return
    if (action === 'go' && !nextCue) return
    setBusy(true)
    setError('')
    try {
      const target = action === 'go' ? (loadedCue ?? undefined) : cueId
      const { event, state } = await api[action](run.id, target)
      setRun((prev) => ({ ...prev, events: [...prev.events, event], state }))
      setLoadedCue(null)
      // The settle effect tweens the states; this adds the flash and the fade bar on top.
      const index = cueList.findIndex((c) => c.id === state.active_cue)
      const card = cardRefs.current[index]
      if (card) {
        gsap.fromTo(card, { ...FLASH.from }, { ...FLASH.to })
        const fade = fadeFor(action, cueList[index])
        gsap.fromTo(card.querySelector('.cue-fade'), { scaleX: 0 }, { scaleX: 1, duration: fade, ease: 'none' })
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
    if (playingBack || ended) return
    setLoadedCue((current) => (current === cueId ? null : cueId))
  }

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
      if (!live || playingBack) return
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
  }, [live, playingBack, act, cueList, run, loadedCue, ended])

  const goLabel = ended ? 'ENDED' : nextCue || cueList.length === 0 ? 'GO' : 'END'
  const nextText = nextCue
    ? `${loadedCue ? 'Loaded' : 'Next'}: Q${nextCue.number} ${nextCue.label}`
    : 'End of cue list'

  return (
    <main className={`board ${playingBack ? 'is-playing-back' : ''}`} ref={scope}>
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
            disabled={playingBack}
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
                  <CueTime cue={c} />
                  <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                  <span className="cue-status">{STATUS[states[i]]}</span>
                  <span className="cue-fade" aria-hidden="true" />
                </button>
              </li>,
            ])}
            {cues && cues.length === 0 && <li className="muted">No cues yet. Switch to Edit to add some.</li>}
          </ol>
        ) : (
          <div className="edit-pane">
            <div className="row edit-tools">
              <button className="ghost small" onClick={() => setImporting(true)}>
                Import CSV…
              </button>
              <button
                className="ghost small"
                onClick={() => api.exportCues(productionId).catch((e) => setError(e.message))}
              >
                Export CSV
              </button>
            </div>
            <CueEditor
              cues={cueList}
              productionId={productionId}
              onSaved={(saved) => afterCueChange(cueList.map((c) => (c.id === saved.id ? saved : c)))}
              onCreated={(created) => afterCueChange([...cueList, created])}
              onDeleted={(id) => afterCueChange(cueList.filter((c) => c.id !== id))}
            />
          </div>
        )}

        <aside className="controls">
          {live ? (
            <>
              <Transport
                disabled={busy || playingBack || !run || ended}
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
              <Playback
                key={run?.id}
                scope={scope}
                cues={cueList}
                events={run?.events ?? []}
                cardRefs={cardRefs}
                markerRef={markerRef}
                fillRef={fillRef}
                active={playingBack}
                onActiveChange={setPlayingBack}
              />
            </>
          ) : (
            <p className="muted edit-help">
              Editing the cue list. Enter or leaving a field saves it; Esc puts it back. The list stays in cue-number
              order. Switch back to Live to run the show.
            </p>
          )}

          <RunPanel
            runs={runs}
            run={run}
            onSelect={onSelectRun}
            onCreate={createRun}
            onEnd={endRun}
            onExport={(id) => api.exportRun(id).catch((e) => setError(e.message))}
          />
          {error && <p className="error">{error}</p>}
        </aside>
      </div>
      {importing && (
        <ImportDialog
          productionId={productionId}
          onClose={() => setImporting(false)}
          onImported={async () => {
            setImporting(false)
            try {
              await afterCueChange(await api.cues(productionId))
            } catch (err) {
              setError(err.message)
            }
          }}
        />
      )}
    </main>
  )
}

/** Time as Eos shows it ("5", "5/3"), with the follow or hang and Eos's total when it says more. */
function CueTime({ cue }) {
  const time = formatTime(cue)
  const total = extraTotal(cue)
  const extra = [cue.follow, total != null && `${formatSeconds(total)} total`].filter(Boolean)
  return (
    <span className="cue-time" title={total != null ? 'Total from Eos, counting delays, discrete times and parts' : undefined}>
      {time || (extra.length ? '' : '–')}
      {extra.length > 0 && <small>{extra.join(' · ')}</small>}
    </span>
  )
}
