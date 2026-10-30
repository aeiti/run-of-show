import { describe, expect, it } from 'vitest'
import { followSlice, liveRun } from './followView'

const cues = [1, 2, 3, 4, 5, 6].map((id) => ({ id, number: String(id) }))
const ids = (list) => list.map((c) => c.id)

describe('liveRun', () => {
  it('follows the newest run still going', () => {
    const runs = [
      { id: 3, ended_at: '2026-10-30T22:00:00Z' },
      { id: 2, ended_at: null },
      { id: 1, ended_at: null },
    ]
    expect(liveRun(runs).id).toBe(2)
  })

  it('falls back to the newest run once they have all ended', () => {
    expect(liveRun([{ id: 2, ended_at: 'x' }, { id: 1, ended_at: 'y' }]).id).toBe(2)
  })

  it('has nothing to follow without runs', () => {
    expect(liveRun([])).toBeNull()
  })
})

describe('followSlice', () => {
  it('shows the standby and what follows it before the first GO', () => {
    const slice = followSlice(cues, { active_cue: null, next_cue: 1 }, 2)
    expect(slice.active).toBeNull()
    expect(slice.standby.id).toBe(1)
    expect(ids(slice.upcoming)).toEqual([2, 3])
  })

  it('counts upcoming cues from the standby, not the active cue', () => {
    // After a GOTO back to 2 the standby is 3, whatever ran before.
    const slice = followSlice(cues, { active_cue: 2, next_cue: 3 }, 2)
    expect([slice.active.id, slice.standby.id]).toEqual([2, 3])
    expect(ids(slice.upcoming)).toEqual([4, 5])
  })

  it('runs out at the end of the list', () => {
    expect(ids(followSlice(cues, { active_cue: 5, next_cue: 6 }).upcoming)).toEqual([])
    const last = followSlice(cues, { active_cue: 6, next_cue: null })
    expect(last.standby).toBeNull()
    expect(last.upcoming).toEqual([])
  })

  it('copes with an active cue that has been deleted', () => {
    const slice = followSlice(cues, { active_cue: null, active_number: '2.5', next_cue: 3 }, 1)
    expect(slice.active).toBeNull()
    expect(ids(slice.upcoming)).toEqual([4])
  })
})
