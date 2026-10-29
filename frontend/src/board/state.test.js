import { describe, expect, it } from 'vitest'
import { cueStates, findByNumber, playheadIndex, sortCues, stepLoad } from './state'

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

describe('loaded cue', () => {
  const state = { active_cue: 2, active_number: '12', next_cue: 3 }

  it('takes the standby place, and the server next cue goes back to pending', () => {
    expect(cueStates(cues, state, 5)).toEqual(['complete', 'active', 'pending', 'pending', 'loaded'])
  })

  it('can load a cue behind the active one without marking it complete', () => {
    expect(cueStates(cues, state, 1)).toEqual(['loaded', 'active', 'pending', 'pending', 'pending'])
  })

  it('arrow keys step the load from the next cue, then from the loaded cue, within the list', () => {
    expect(stepLoad(cues, state, null, 1)).toBe(4) // next is 12.5 -> 20
    expect(stepLoad(cues, state, 4, -1)).toBe(3)
    expect(stepLoad(cues, state, 5, 1)).toBe(5) // stays on the last cue
    expect(stepLoad(cues, state, 1, -1)).toBe(1) // stays on the first cue
  })

  it('finds a cue by number however it is typed', () => {
    expect(findByNumber(cues, '12.50')?.id).toBe(3)
    expect(findByNumber(cues, ' 100 ')?.id).toBe(5)
    expect(findByNumber(cues, '13')).toBeNull()
    expect(findByNumber(cues, 'abc')).toBeNull()
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
