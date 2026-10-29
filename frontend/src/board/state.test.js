import { describe, expect, it } from 'vitest'
import { cueStates, playheadIndex, sortCues } from './state'

const cues = sortCues([
  { id: 5, number: '100' },
  { id: 3, number: '12.5' },
  { id: 1, number: '1' },
  { id: 2, number: '12' },
  { id: 4, number: '20' },
])

describe('sortCues', () => {
  it('orders numerically, not as text', () => {
    expect(cues.map((c) => c.number)).toEqual(['1', '12', '12.5', '20', '100'])
  })
})

describe('cueStates', () => {
  it('marks everything pending except the standby before the first GO', () => {
    expect(cueStates(cues, { active_cue: null, active_number: null, next_cue: 1 })).toEqual([
      'standby', 'pending', 'pending', 'pending', 'pending',
    ])
  })

  it('marks cues below the active number complete', () => {
    expect(cueStates(cues, { active_cue: 3, active_number: '12.5', next_cue: 4 })).toEqual([
      'complete', 'complete', 'active', 'standby', 'pending',
    ])
  })

  it('after a BACK or GOTO, cues past the active one are pending again', () => {
    expect(cueStates(cues, { active_cue: 2, active_number: '12', next_cue: 3 })).toEqual([
      'complete', 'active', 'standby', 'pending', 'pending',
    ])
  })

  it('still marks complete cues by number when the active cue was deleted', () => {
    // Cue 12.5 was active and then deleted: no active card, but 1 and 12 are done.
    const remaining = cues.filter((c) => c.id !== 3)
    expect(cueStates(remaining, { active_cue: null, active_number: '12.5', next_cue: 4 })).toEqual([
      'complete', 'complete', 'standby', 'pending',
    ])
  })
})

describe('playheadIndex', () => {
  it('is -1 before the first GO', () => {
    expect(playheadIndex(cues, { active_number: null })).toBe(-1)
  })

  it('sits on the active cue', () => {
    expect(playheadIndex(cues, { active_number: '20' })).toBe(3)
  })

  it('falls back to the last cue before a deleted active cue', () => {
    const remaining = cues.filter((c) => c.id !== 3)
    expect(playheadIndex(remaining, { active_number: '12.5' })).toBe(1)
  })
})
