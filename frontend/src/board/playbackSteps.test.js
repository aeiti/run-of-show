import { describe, expect, it } from 'vitest'
import { formatClock, previewSteps, recordedSteps } from './playbackSteps'

const cues = [
  { id: 1, number: '1' },
  { id: 2, number: '2' },
  { id: 3, number: '12.5' },
]

const at = (seconds) => new Date(Date.UTC(2026, 10, 14, 19, 30, seconds)).toISOString()

describe('recordedSteps', () => {
  it('places each event at its real offset from the first, in seconds', () => {
    const steps = recordedSteps(
      [
        { fired_at: at(0), action: 'go', cue_number: '1' },
        { fired_at: at(7), action: 'go', cue_number: '2' },
        { fired_at: at(40), action: 'back', cue_number: '1' },
      ],
      cues,
    )
    expect(steps.map((s) => s.t)).toEqual([0, 7, 40])
    expect(steps.map((s) => s.state.active_cue)).toEqual([1, 2, 1])
    expect(steps[1].state.next_cue).toBe(3)
  })

  it('clears the active cue on a reset', () => {
    const [, reset] = recordedSteps(
      [
        { fired_at: at(0), action: 'go', cue_number: '2' },
        { fired_at: at(3), action: 'reset', cue_number: null },
      ],
      cues,
    )
    expect(reset.state).toEqual({ active_cue: null, active_number: null, next_cue: 1 })
  })

  it('plays a since-deleted cue by its recorded number', () => {
    const [step] = recordedSteps([{ fired_at: at(0), action: 'go', cue_number: '1.5' }], cues)
    expect(step.state).toEqual({ active_cue: null, active_number: '1.5', next_cue: 2 })
  })

  it('is empty for a run with no events', () => {
    expect(recordedSteps([], cues)).toEqual([])
  })
})

describe('previewSteps', () => {
  it('steps through every cue evenly', () => {
    const steps = previewSteps(cues, 0.5)
    expect(steps.map((s) => [s.t, s.state.active_cue])).toEqual([
      [0, 1],
      [0.5, 2],
      [1, 3],
    ])
  })
})

describe('formatClock', () => {
  it('shows minutes and seconds, and hours when needed', () => {
    expect(formatClock(0)).toBe('0:00')
    expect(formatClock(75.9)).toBe('1:15')
    expect(formatClock(3723)).toBe('1:02:03')
  })
})
