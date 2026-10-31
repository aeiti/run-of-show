import { describe, expect, it } from 'vitest'
import { extraTotal, fadeFor, fadeSeconds, formatSeconds, formatTime, parseTimeInput, progressFade } from './cueTime'

const cue = (time, down_time = null, duration = null) => ({ time, down_time, duration })

describe('formatSeconds', () => {
  it('writes a minute or more as m:ss, like Eos', () => {
    expect(formatSeconds('3.9')).toBe('3.9')
    expect(formatSeconds('0')).toBe('0')
    expect(formatSeconds('60')).toBe('1:00')
    expect(formatSeconds('90.5')).toBe('1:30.5')
    expect(formatSeconds(null)).toBe('')
  })
})

describe('formatTime', () => {
  it('shows up/down only when the down time differs', () => {
    expect(formatTime(cue('5'))).toBe('5')
    expect(formatTime(cue('5', '5'))).toBe('5')
    expect(formatTime(cue('5', '120'))).toBe('5/2:00')
    expect(formatTime(cue(null, null, '13'))).toBe('') // a part cue: no time of its own
  })
})

describe('fadeSeconds and extraTotal', () => {
  it("prefers Eos's total, which counts delays, discrete times and parts", () => {
    expect(fadeSeconds(cue('5', null, '13'))).toBe(13)
    expect(fadeSeconds(cue('2', '6'))).toBe(6)
    expect(fadeSeconds(cue('0'))).toBe(0)
    expect(fadeSeconds(cue(null))).toBeNull()

    expect(extraTotal(cue('5', null, '13'))).toBe(13)
    expect(extraTotal(cue(null, null, '13'))).toBe(13)
    expect(extraTotal(cue('5', null, '5'))).toBeNull()
    expect(extraTotal(cue('2', '6', '2'))).toBeNull() // Eos can total less than the down time
  })

  it('runs BACK for a fixed second, and untimed cues instantly', () => {
    expect(fadeFor('back', cue('5', null, '13'))).toBe(1)
    expect(fadeFor('goto', cue('5', null, '13'))).toBe(13)
    expect(fadeFor('go', cue(null))).toBe(0)
  })
})

describe('parseTimeInput', () => {
  it('reads seconds, m:ss and up/down', () => {
    expect(parseTimeInput('5')).toEqual({ time: '5', down_time: null })
    expect(parseTimeInput(' 3.5 / 1:00 ')).toEqual({ time: '3.5', down_time: '60' })
    expect(parseTimeInput('1:02:03')).toEqual({ time: '3723', down_time: null })
    expect(parseTimeInput('')).toEqual({ time: null, down_time: null })
  })

  it('refuses anything else', () => {
    for (const bad of ['abc', '-1', '1:75', '5/', '5/3/1', '/3']) expect(() => parseTimeInput(bad)).toThrow(/5\/3/)
  })
})

describe('progressFade', () => {
  const sample = (progress, at, remaining = null, cue = 4) => ({ cue, progress, remaining, at })

  it('uses the time left when Eos gives it', () => {
    expect(progressFade(sample(0.5, 10, 5), null, 12)).toEqual({ from: 0.5, duration: 5 })
  })

  it('otherwise keeps the pace since the previous sample of the same cue', () => {
    // 10% to 30% in 2 s is 10% a second: 70% left takes 7 s.
    const { from, duration } = progressFade(sample(0.3, 12), sample(0.1, 10), 60)
    expect(from).toBe(0.3)
    expect(duration).toBeCloseTo(7)
  })

  it('falls back to what is left of the cue time', () => {
    expect(progressFade(sample(0.25, 12), null, 8)).toEqual({ from: 0.25, duration: 6 })
    // A previous sample of another cue, or no progress since, says nothing about the pace.
    expect(progressFade(sample(0.25, 12), sample(0.1, 10, null, 3), 8)).toEqual({ from: 0.25, duration: 6 })
    expect(progressFade(sample(0.25, 12), sample(0.25, 10), 8)).toEqual({ from: 0.25, duration: 6 })
    expect(progressFade(sample(0.25, 12), null, null)).toEqual({ from: 0.25, duration: 0 })
  })

  it('is full and done at 100%', () => {
    expect(progressFade(sample(1, 12, 3), sample(0.5, 10), 8)).toEqual({ from: 1, duration: 0 })
  })
})
