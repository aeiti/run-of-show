// Pure helpers that turn a run's event log into timed board states for playback.

const numberOf = (cue) => Number(cue.number)

/** The run state after an event: what the server would have reported at that moment. */
function stateAfter(cues, activeNumber) {
  // After a reset activeNumber is null, which becomes 0: no cue matches (the
  // API only accepts numbers above 0), and the next cue is the first one.
  const value = Number(activeNumber)
  const active = cues.find((c) => numberOf(c) === value)
  const next = cues.find((c) => numberOf(c) > value)
  return { active_cue: active?.id ?? null, active_number: activeNumber, next_cue: next?.id ?? null }
}

/**
 * One step per event, at its real offset in seconds from the first event.
 * Uses the event's snapshotted number, so a cue edited or deleted since the
 * run still plays back where it was.
 */
export function recordedSteps(events, cues) {
  if (!events.length) return []
  const start = Date.parse(events[0].fired_at)
  return events.map((e) => ({
    t: (Date.parse(e.fired_at) - start) / 1000,
    action: e.action,
    state: stateAfter(cues, e.cue_number),
  }))
}

/** Evenly spaced steps through every cue, for a run with nothing recorded yet. */
export function previewSteps(cues, gap = 0.8) {
  return cues.map((c, i) => ({ t: i * gap, action: 'go', state: stateAfter(cues, c.number) }))
}

/** 75.4 -> "1:15", 3723 -> "1:02:03". */
export function formatClock(seconds) {
  const s = Math.max(0, Math.floor(seconds))
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  const ss = String(s % 60).padStart(2, '0')
  return h ? `${h}:${String(m).padStart(2, '0')}:${ss}` : `${m}:${ss}`
}
