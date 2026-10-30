// Pure helpers for the follow view: which run to follow, and which cues to show.

/**
 * The run a follow screen shows: the newest one still going, or failing that
 * the newest one. `runs` is newest first, as the API returns it.
 */
export function liveRun(runs) {
  return runs.find((r) => !r.ended_at) ?? runs[0] ?? null
}

/**
 * The active cue, the cue in standby, and the `count` cues after that, from
 * the server's run state. Before the first GO there is no active cue; at the
 * end of the list there is no standby.
 */
export function followSlice(cues, state, count = 4) {
  const active = cues.find((c) => c.id === state?.active_cue) ?? null
  const standby = cues.find((c) => c.id === state?.next_cue) ?? null
  const from = standby ? cues.indexOf(standby) + 1 : cues.length
  return { active, standby, upcoming: cues.slice(from, from + count) }
}
