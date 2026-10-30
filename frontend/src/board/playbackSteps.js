// Pure helpers that turn a run's event log into timed board states for playback.

import { fadeFor, fadeSeconds } from './cueTime'

const numberOf = (cue) => Number(cue.number)

// The actions that move the active cue. A hold or resume only records it.
const MOVES = new Set(['go', 'back', 'goto', 'reset'])

/** The run state after an event: what the server would have reported at that moment. */
function stateAfter(cues, activeNumber) {
  // After a reset activeNumber is null, which becomes 0: no cue matches (the
  // API only accepts numbers above 0), and the next cue is the first one.
  const value = Number(activeNumber)
  const active = cues.find((c) => numberOf(c) === value)
  const next = cues.find((c) => numberOf(c) > value)
  return { active_cue: active?.id ?? null, active_number: activeNumber, next_cue: next?.id ?? null }
}

/** Seconds the active cue's fade bar runs for after this action. */
function fadeOf(cues, action, state) {
  const cue = cues.find((c) => c.id === state.active_cue)
  return cue ? fadeFor(action, cue) : 0
}

const offset = (events, e) => (Date.parse(e.fired_at) - Date.parse(events[0].fired_at)) / 1000

/**
 * One step per cue action, at its real offset in seconds from the first event.
 * Uses the event's snapshotted number, so a cue edited or deleted since the
 * run still plays back where it was. Fades use the cue's current time. Holds
 * are left out: they never change the cues (see holdSpans).
 */
export function recordedSteps(events, cues) {
  if (!events.length) return []
  const start = Date.parse(events[0].fired_at)
  return events.filter((e) => MOVES.has(e.action)).map((e) => {
    const state = stateAfter(cues, e.cue_number)
    return { t: (Date.parse(e.fired_at) - start) / 1000, action: e.action, state, fade: fadeOf(cues, e.action, state) }
  })
}

/**
 * Each hold as { t, end, reason, cue_number }, in seconds from the first
 * event like recordedSteps. `end` is null for a hold never resumed.
 */
export function holdSpans(events) {
  const spans = []
  for (const e of events) {
    if (e.action === 'hold') spans.push({ t: offset(events, e), end: null, reason: e.note, cue_number: e.cue_number })
    else if (e.action === 'resume' && spans.at(-1)?.end === null) spans.at(-1).end = offset(events, e)
  }
  return spans
}

/**
 * A GO through every cue, for a run with nothing recorded yet. Each cue gets
 * its own fade time before the next GO, and never less than `gap`.
 */
export function previewSteps(cues, gap = 0.8) {
  let t = 0
  return cues.map((c) => {
    const fade = fadeSeconds(c) ?? 0
    const step = { t, action: 'go', state: stateAfter(cues, c.number), fade }
    t += Math.max(gap, fade)
    return step
  })
}

/** 75.4 -> "1:15", 3723 -> "1:02:03". */
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
