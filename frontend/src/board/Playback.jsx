import { useRef, useState } from 'react'
import gsap from 'gsap'
import { useGSAP } from '@gsap/react'
import { FLASH, LOOK, playheadPos } from './looks'
import { formatClock, previewSteps, recordedSteps } from './playbackSteps'
import { cueStates, playheadIndex } from './state'

const SPEEDS = [1, 2, 5, 20]

/**
 * Replays a run on the board with one gsap.timeline(): every cue look change
 * and playhead move is a tween at the moment it happened, so play, pause,
 * speed (timeScale) and scrubbing (progress) all come from GSAP itself.
 * Nothing here talks to the API; playback never writes to the log.
 */
export default function Playback({ scope, cues, events, cardRefs, markerRef, fillRef, active, onActiveChange }) {
  const [playing, setPlaying] = useState(false)
  const [speed, setSpeed] = useState(1)
  const tl = useRef(null)
  const scrubRef = useRef(null)
  const clockRef = useRef(null)

  const { contextSafe } = useGSAP({ scope })
  const recorded = events.length > 0

  // Write progress straight to the DOM: onUpdate runs every frame, and a
  // React state update there would re-render the board 60 times a second.
  function showProgress(timeline) {
    if (scrubRef.current) scrubRef.current.value = Math.round(timeline.progress() * 1000)
    if (clockRef.current) {
      clockRef.current.textContent = `${formatClock(timeline.time())} / ${formatClock(timeline.duration())}`
    }
  }

  const build = contextSafe(() => {
    const cards = cardRefs.current.slice(0, cues.length)
    const n = cards.length
    const steps = recorded ? recordedSteps(events, cues) : previewSteps(cues)
    const timeline = gsap.timeline({
      paused: true,
      onUpdate() {
        showProgress(this)
      },
      onComplete: () => setPlaying(false),
    })

    let looks = cueStates(cues, { active_cue: null, active_number: null, next_cue: cues[0]?.id ?? null })
    // Always pass GSAP a copy: it writes into the vars object (e.g. duration),
    // and LOOK is shared and frozen.
    cards.forEach((card, i) => timeline.set(card, { ...LOOK[looks[i]] }, 0))
    timeline.set(markerRef.current, { left: '0%' }, 0)
    timeline.set(fillRef.current, { width: '0%' }, 0)

    // Lead-in so the first cue isn't already firing at 0:00.
    const lead = 0.6
    for (const step of steps) {
      const at = step.t + lead
      const next = cueStates(cues, step.state)
      cards.forEach((card, i) => {
        if (next[i] !== looks[i]) timeline.to(card, { ...LOOK[next[i]], duration: 0.35, ease: 'power2.out' }, at)
      })
      const card = cards[cues.findIndex((c) => c.id === step.state.active_cue)]
      // immediateRender: false, or every card would show its flash start state at t=0.
      if (card) timeline.fromTo(card, { ...FLASH.from }, { ...FLASH.to, immediateRender: false }, at)
      const pos = playheadPos(playheadIndex(cues, step.state), n)
      timeline.to(markerRef.current, { left: pos, duration: 0.4, ease: 'power3.inOut' }, at)
      timeline.to(fillRef.current, { width: pos, duration: 0.4, ease: 'power3.inOut' }, at)
      looks = next
    }
    timeline.to({}, { duration: 1 })
    timeline.timeScale(speed)
    return timeline
  })

  const start = contextSafe(() => {
    if (!cues.length) return
    tl.current?.kill()
    tl.current = build()
    onActiveChange(true)
    tl.current.play(0)
    setPlaying(true)
  })

  const toggle = contextSafe(() => {
    const timeline = tl.current
    if (!timeline) return start()
    if (timeline.progress() === 1) timeline.restart()
    else timeline.paused(!timeline.paused())
    setPlaying(!timeline.paused())
  })

  const stop = contextSafe(() => {
    tl.current?.kill()
    tl.current = null
    setPlaying(false)
    onActiveChange(false) // the board settles back to the live run state
  })

  const scrub = contextSafe((value) => {
    if (!tl.current) start()
    tl.current.pause()
    tl.current.progress(value / 1000)
    setPlaying(false)
  })

  function changeSpeed(value) {
    setSpeed(value)
    tl.current?.timeScale(value)
  }

  const what = recorded ? `Recorded run · ${events.length} events` : 'Nothing recorded yet · evenly spaced preview'

  if (!active) {
    return (
      <div className="playback">
        <button className="ghost wide" onClick={start} disabled={!cues.length}>
          {recorded ? '▶ Play back this run' : '▶ Preview run'}
        </button>
      </div>
    )
  }

  return (
    <div className="playback on">
      <p className="preview-banner">PLAYBACK · not recorded</p>
      <p className="muted small-print">{what}</p>
      <div className="row">
        <button className="ghost" onClick={toggle} aria-label={playing ? 'Pause' : 'Play'}>
          {playing ? '❚❚' : '▶'}
        </button>
        <div className="speeds" role="group" aria-label="Speed">
          {SPEEDS.map((s) => (
            <button key={s} className={`ghost ${s === speed ? 'on' : ''}`} aria-pressed={s === speed} onClick={() => changeSpeed(s)}>
              {s}×
            </button>
          ))}
        </div>
        <button className="ghost" onClick={stop} aria-label="Stop playback">
          ■
        </button>
      </div>
      <input
        ref={scrubRef}
        className="scrub"
        type="range"
        min="0"
        max="1000"
        defaultValue="0"
        aria-label="Scrub"
        onInput={(e) => scrub(Number(e.target.value))}
      />
      <p className="muted clock" ref={clockRef}>
        0:00
      </p>
    </div>
  )
}
