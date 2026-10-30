import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { api } from './api'
import { follow } from './live'
import CueEditor from './board/CueEditor'
import FilesDialog from './board/FilesDialog'
import PeopleDialog from './board/PeopleDialog'
import { can } from './access'
import Unavailable from './Unavailable'
import ImportDialog from './board/ImportDialog'
import ProductionHeader from './board/ProductionHeader'
import Playback from './board/Playback'
import RunPanel from './board/RunPanel'
import ScriptViewer from './board/ScriptViewer'
import Transport from './board/Transport'
import { currentScript } from './board/files'
import { extraTotal, fadeFor, formatSeconds, formatTime } from './board/cueTime'
import { FLASH, LOOK, STATUS, playheadPos } from './board/looks'
import { cueStates, findByNumber, playheadIndex, sortCues, stepLoad } from './board/state'
import { sceneSpans, trackLabels } from './board/track'

gsap.registerPlugin(useGSAP)
// The fade bars are timers: after a stalled frame they should jump to where
// real time says they are, not resume slowly as GSAP does by default.
gsap.ticker.lagSmoothing(0)

// GSAP owns each card's look (on .cue-inner); React only renders content.
// The entrance animates the outer <li>, so the two never tween the same property.
// Each card's .cue-fade bar fills over the cue's time after it goes, so the
// operator can see when a cue has finished; a later action cuts it off.

export default function Board({ productionId, runId, me, onBack, onSelectRun, onSignedOut }) {
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
  const [showPeople, setShowPeople] = useState(false)
  const [liveStatus, setLiveStatus] = useState('connecting')
  const [files, setFiles] = useState([])
  const [showFiles, setShowFiles] = useState(false)
  const [showScript, setShowScript] = useState(false)
  // No such production, or access to it was lost (the server doesn't say which).
  const [gone, setGone] = useState(false)

  const scope = useRef(null)
  const cardRefs = useRef([])
  const markerRef = useRef(null)
  const fillRef = useRef(null)
  const trackRef = useRef(null)
  const gotoRef = useRef(null)
  const noteRef = useRef(null)
  // Event ids already on the board. An action can arrive twice, from its own
  // response and from the live socket (in either order); it plays once.
  const seenEvents = useRef(new Set())

  const cueList = useMemo(() => cues ?? [], [cues])
  const loaded = Boolean(production && cues && run)
  const live = mode === 'live'
  const ended = Boolean(run?.ended_at)
  const hold = run?.state.hold ?? null
  // This run's cue notes, shown on each cue's card.
  const notesByCue = useMemo(() => Object.groupBy(run?.cue_notes ?? [], (n) => n.cue), [run])
  // What this user's role on the production allows; the server checks it too.
  const canOperate = can(production?.role, 'operate')
  const canEdit = can(production?.role, 'edit')
  // The latest script, shown beside the cue list at the active cue's page.
  const script = useMemo(() => currentScript(files), [files])
  const scriptPage = cueList.find((c) => c.id === run?.state.active_cue)?.page ?? null

  // The server decides the active and next cue; the board looks them up and
  // overlays the operator's loaded cue, which only exists on this screen.
  const states = useMemo(() => cueStates(cueList, run?.state, loadedCue), [cueList, run, loadedCue])
  const playIdx = useMemo(() => playheadIndex(cueList, run?.state), [cueList, run])
  const nextCue = cueList.find((c) => c.id === (loadedCue ?? run?.state.next_cue))
  const gotoTarget = findByNumber(cueList, gotoText)
  const canBack =
    run?.state.active_number != null && cueList.some((c) => Number(c.number) < Number(run.state.active_number))

  // Which cue numbers fit on the track depends on how wide it is.
  const [trackWidth, setTrackWidth] = useState(0)
  useEffect(() => {
    const el = trackRef.current
    if (!el) return
    const ro = new ResizeObserver(([entry]) => setTrackWidth(entry.contentRect.width))
    ro.observe(el)
    return () => ro.disconnect()
  }, [loaded])
  const labels = useMemo(() => trackLabels(cueList, trackWidth), [cueList, trackWidth])
  const scenes = useMemo(() => sceneSpans(cueList, trackWidth), [cueList, trackWidth])
  const pct = (count) => `${(count / cueList.length) * 100}%`

  useEffect(() => {
    let cancelled = false
    Promise.all([api.production(productionId), api.cues(productionId), api.runs(productionId)])
      .then(async ([p, c, r]) => {
        if (cancelled) return
        setProduction(p)
        setCues(c)
        setRuns(r)
        // No run in the URL: open the latest one, or start "Run 1" if allowed to.
        if (!runId && (r.length || can(p.role, 'operate'))) {
          const target = r[0] ?? (await api.createRun(productionId, { label: 'Run 1' }))
          if (!r.length) setRuns([target])
          onSelectRun(target.id, { replace: true })
        }
      })
      .catch((e) => (e.status === 404 ? setGone(true) : setError(e.message)))
    return () => {
      cancelled = true
    }
    // Only on a new production: runId changes are handled by the effect below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [productionId])

  // Apart from the board's own data, so a problem with files doesn't stop the show.
  useEffect(() => {
    let cancelled = false
    api
      .files(productionId)
      .then((f) => !cancelled && setFiles(f))
      .catch((e) => setError(e.message))
    return () => {
      cancelled = true
    }
  }, [productionId])

  useEffect(() => {
    if (!runId) return
    let cancelled = false
    api
      .run(runId)
      .then((r) => {
        if (cancelled) return
        if (r.production !== productionId) throw new Error('That run belongs to another production.')
        showRun(r)
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

  function showRun(r) {
    seenEvents.current = new Set(r.events.map((e) => e.id))
    setRun(r)
  }

  // Put one event on the board: append it, take the new state, and for a cue
  // change flash the card and start its fade bar. Ignores an event already shown.
  const applyEvent = contextSafe((event, state) => {
    if (seenEvents.current.has(event.id)) return
    seenEvents.current.add(event.id)
    // The first GO or GOTO starts the run; the server records the same time.
    const starts = !run?.started_at && (event.action === 'go' || event.action === 'goto')
    setRun((prev) => ({
      ...prev,
      events: [...prev.events, event],
      state,
      ...(starts && { started_at: event.fired_at }),
    }))
    if (starts) setRuns((prev) => prev.map((r) => (r.id === event.run ? { ...r, started_at: event.fired_at } : r)))
    // A hold or resume leaves the cues (and the loaded cue) as they are.
    if (event.action === 'hold' || event.action === 'resume') return
    // Someone fired the cue this screen had loaded: nothing left to load.
    setLoadedCue((current) => (current === state.active_cue ? null : current))
    if (!live || playingBack) return
    // The settle effect tweens the states; this adds the flash and the fade bar on top.
    const index = cueList.findIndex((c) => c.id === state.active_cue)
    const card = cardRefs.current[index]
    if (card) {
      gsap.fromTo(card, { ...FLASH.from }, { ...FLASH.to })
      const fade = fadeFor(event.action, cueList[index])
      gsap.fromTo(card.querySelector('.cue-fade'), { scaleX: 0 }, { scaleX: 1, duration: fade, ease: 'none' })
      card.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
    }
  })

  // GO, BACK, GOTO, RESET, HOLD and RESUME all append one event and return
  // the new state. `arg` is the cue for GOTO and the reason for HOLD.
  // Resolves to whether the action went through.
  const act = contextSafe(async (action, arg) => {
    if (!live || busy || playingBack || !run || ended || !canOperate) return false
    // Held: only RESUME. Not held: anything but RESUME.
    if (Boolean(hold) !== (action === 'resume')) return false
    if (action === 'go' && !nextCue) return false
    setBusy(true)
    setError('')
    try {
      const target = action === 'go' ? (loadedCue ?? undefined) : arg
      const { event, state } = await api[action](run.id, target)
      applyEvent(event, state)
      if (action !== 'hold' && action !== 'resume') setLoadedCue(null)
      return true
    } catch (e) {
      setError(e.message)
      return false
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

  // Corrected times; resolves to whether it saved.
  async function updateRun(data) {
    try {
      const updated = await api.updateRun(run.id, data)
      setRun((prev) => ({ ...prev, ...updated }))
      setRuns((prev) => prev.map((r) => (r.id === updated.id ? updated : r)))
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  // Cue notes: each resolves to whether it worked, so the form knows to clear.
  async function noteAction(fn, update) {
    try {
      const result = await fn()
      setRun((prev) => ({ ...prev, cue_notes: update(prev.cue_notes, result) }))
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }
  const addNote = (cue, text) => noteAction(() => api.addCueNote(run.id, { cue, text }), (notes, n) => [...notes, n])
  const editNote = (id, text) =>
    noteAction(
      () => api.updateCueNote(id, { text }),
      (notes, n) => notes.map((x) => (x.id === id ? n : x)),
    )
  const deleteNote = (id) =>
    noteAction(
      () => api.deleteCueNote(id),
      (notes) => notes.filter((x) => x.id !== id),
    )

  // Any cue edit can change which cue is next, so refresh the run state after it.
  async function afterCueChange(nextCues) {
    setCues(sortCues(nextCues))
    try {
      showRun(await api.run(run.id))
    } catch (err) {
      setError(err.message)
    }
  }

  // Live updates from other screens (frontend/src/live.js). A ref, so the
  // socket set up once per production always calls the latest handler.
  const onLive = useRef(null)
  onLive.current = async (message) => {
    const current = run?.id
    const refreshRun = async () => {
      if (current == null) return
      const r = await api.run(current)
      // Only if the board is still on that run.
      setRun((prev) => {
        if (prev?.id !== r.id) return prev
        seenEvents.current = new Set(r.events.map((e) => e.id))
        return r
      })
    }
    try {
      switch (message.type) {
        case 'run.event':
          if (message.run === current) applyEvent(message.event, message.state)
          break
        case 'runs':
          setRuns(await api.runs(productionId))
          if (message.run === current) await refreshRun()
          break
        case 'notes':
          if (message.run === current) await refreshRun()
          break
        case 'files':
          setFiles(await api.files(productionId))
          break
        case 'cues':
          setCues(sortCues(await api.cues(productionId)))
          await refreshRun()
          break
        case 'production':
        case 'access':
          // The role may have changed, and with it what this board offers.
          setProduction(await api.production(productionId))
          break
        case 'production.deleted':
          setGone(true)
          break
        case 'resync': {
          const [p, c, r] = await Promise.all([api.production(productionId), api.cues(productionId), api.runs(productionId)])
          setProduction(p)
          setCues(sortCues(c))
          setRuns(r)
          await refreshRun()
          setFiles(await api.files(productionId))
          break
        }
      }
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
        onGone: () => setGone(true),
        onSignedOut,
      }),
    // One socket per production; the handlers read the latest state through onLive.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [productionId],
  )

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
      } else if (e.key === 'n') {
        e.preventDefault()
        noteRef.current?.focus()
      } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        if (!ended) setLoadedCue(stepLoad(cueList, run?.state, loadedCue, e.key === 'ArrowDown' ? 1 : -1))
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [live, playingBack, act, cueList, run, loadedCue, ended])

  const goLabel = ended ? 'ENDED' : hold ? 'HOLD' : nextCue || cueList.length === 0 ? 'GO' : 'END'
  const nextText = nextCue
    ? `${loadedCue ? 'Loaded' : 'Next'}: Q${nextCue.number} ${nextCue.label}`
    : 'End of cue list'

  if (gone) return <Unavailable me={me} />
  return (
    <main className={`board ${playingBack ? 'is-playing-back' : ''}`} ref={scope}>
      <div className="board-head">
        <button className="ghost" onClick={onBack}>
          ← Productions
        </button>
        <ProductionHeader
          production={production}
          onSaved={setProduction}
          onDeleted={onBack}
          onPeople={() => setShowPeople(true)}
          onFiles={() => setShowFiles(true)}
          onScript={script && (() => setShowScript(!showScript))}
          scriptShown={showScript}
        />
        <span
          className={`sync-status ${liveStatus}`}
          role="status"
          title={
            liveStatus === 'live'
              ? 'Changes from other screens appear here as they happen'
              : 'Not receiving changes from other screens; this board reloads when it reconnects'
          }
        >
          {liveStatus === 'live' ? 'Synced' : liveStatus === 'connecting' ? 'Connecting…' : 'Reconnecting…'}
        </span>
        <Link
          className="button ghost small follow-link"
          to={`/productions/${productionId}/follow`}
          title="A read-only view of the live run, for tablets backstage"
        >
          Follow view
        </Link>
        <div className="mode-toggle" role="group" aria-label="Board mode" hidden={!canEdit}>
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

      <div className="track" aria-hidden="true" ref={trackRef}>
        {scenes.map((s, k) => (
          <div
            key={s.start}
            className={`track-scene${k % 2 ? ' alt' : ''}`}
            style={{ left: pct(s.start), width: pct(s.end - s.start) }}
            title={s.name}
          >
            {s.labelled && <span>{s.name}</span>}
          </div>
        ))}
        <div className="track-fill" ref={fillRef} />
        {labels.map((l) => (
          <span key={cueList[l.index].id}>
            <span className="tick" style={{ left: l.x }} />
            <span className="tick-label" style={{ left: l.left }}>
              {cueList[l.index].number}
            </span>
          </span>
        ))}
        <div className="playhead" ref={markerRef} />
      </div>

      <div className={`board-body${script && showScript ? ' with-script' : ''}`}>
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
                    {notesByCue[c.id]?.map((n) => (
                      <small key={n.id} className="run-note">
                        ✎ {n.text}
                      </small>
                    ))}
                  </span>
                  <CueTime cue={c} />
                  <span className="cue-page">{c.page ? `p.${c.page}` : ''}</span>
                  <span className="cue-status">{STATUS[states[i]]}</span>
                  <span className="cue-fade" aria-hidden="true" />
                </button>
              </li>,
            ])}
            {cues && cues.length === 0 && (
              <li className="muted empty-cues">
                {canEdit ? (
                  <>
                    No cues yet.{' '}
                    <button className="small" onClick={() => setImporting(true)}>
                      Import from Eos…
                    </button>{' '}
                    or switch to Edit to type them in.
                  </>
                ) : (
                  'No cues yet.'
                )}
              </li>
            )}
          </ol>
        ) : (
          <div className="edit-pane">
            <div className="row edit-tools">
              <button className="ghost small" onClick={() => setImporting(true)}>
                Import from Eos or CSV…
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

        {script && showScript && <ScriptViewer file={script} page={scriptPage} />}

        <aside className="controls">
          {live ? (
            <>
              <Transport
                disabled={busy || playingBack || !run || ended || !canOperate}
                hold={hold}
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
            cues={cueList}
            canOperate={canOperate}
            noteCueNumber={cueList.find((c) => c.id === loadedCue)?.number ?? run?.state.active_number ?? ''}
            noteRef={noteRef}
            onAddNote={addNote}
            onEditNote={editNote}
            onDeleteNote={deleteNote}
            onSelect={onSelectRun}
            onCreate={createRun}
            onEnd={endRun}
            onUpdate={updateRun}
            onExport={(id) => api.exportRun(id).catch((e) => setError(e.message))}
          />
          {error && <p className="error">{error}</p>}
        </aside>
      </div>
      {showPeople && (
        <PeopleDialog production={production} me={me} onClose={() => setShowPeople(false)} onLeft={onBack} />
      )}
      {showFiles && (
        <FilesDialog production={production} files={files} onChange={setFiles} onClose={() => setShowFiles(false)} />
      )}
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
