// Pure helpers for the board. The server decides the run state; these only
// turn { active_cue, active_number, next_cue } into a look for each cue.

export const byNumber = (a, b) => Number(a.number) - Number(b.number)

export function sortCues(cues) {
  return [...cues].sort(byNumber)
}

/**
 * One of 'complete' | 'active' | 'standby' | 'pending' per cue, in list order.
 *
 * "Complete" is decided by number rather than by position, so it is still
 * right when the active cue has been deleted (active_cue is null but
 * active_number remains), and after a BACK or GOTO. A cue whose number equals
 * active_number is always the server's active_cue, so it is caught by the
 * first check and never reaches the "complete" comparison.
 */
export function cueStates(cues, state) {
  const activeNumber = state?.active_number == null ? null : Number(state.active_number)
  return cues.map((cue) => {
    if (cue.id === state?.active_cue) return 'active'
    if (cue.id === state?.next_cue) return 'standby'
    if (activeNumber !== null && Number(cue.number) < activeNumber) return 'complete'
    return 'pending'
  })
}

/** Where the playhead sits: the index of the last cue at or before the active number, or -1. */
export function playheadIndex(cues, state) {
  if (state?.active_number == null) return -1
  const active = Number(state.active_number)
  return cues.reduce((acc, cue, i) => (Number(cue.number) <= active ? i : acc), -1)
}
