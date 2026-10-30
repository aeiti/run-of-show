import { describe, expect, it } from 'vitest'
import {
  formatDateRange,
  formatLateness,
  fromLocalInput,
  keepSeconds,
  minutesLate,
  secondsBetween,
  toLocalInput,
} from './dates'

// ICU versions differ in the (thin, narrow or no) spaces around the dash.
const plain = (s) => s.replace(/\s*–\s*/g, ' – ').replace(/\s/g, ' ')

describe('formatDateRange', () => {
  it('writes opening and closing as one range', () => {
    expect(plain(formatDateRange('2026-11-14', '2026-11-29', 'en-GB'))).toBe('14 – 29 Nov 2026')
    expect(plain(formatDateRange('2026-11-14', '2026-12-05', 'en-GB'))).toBe('14 Nov – 5 Dec 2026')
    expect(plain(formatDateRange('2026-12-30', '2027-01-02', 'en-GB'))).toBe('30 Dec 2026 – 2 Jan 2027')
  })

  it('writes a one-night show as one date', () => {
    expect(formatDateRange('2026-11-14', '2026-11-14', 'en-GB')).toBe('14 Nov 2026')
  })

  it('says which date it is when only one is known', () => {
    expect(formatDateRange('2026-11-14', null, 'en-GB')).toBe('Opens 14 Nov 2026')
    expect(formatDateRange(null, '2026-11-29', 'en-GB')).toBe('Closes 29 Nov 2026')
    expect(formatDateRange(null, null, 'en-GB')).toBe('')
  })

  it('reads the dates as local days, not UTC midnight', () => {
    // In a timezone west of UTC, new Date('2026-11-01') is 31 October.
    expect(formatDateRange('2026-11-01', null, 'en-GB')).toBe('Opens 1 Nov 2026')
  })
})

describe('datetime-local inputs', () => {
  it('round-trips a time to the minute', () => {
    const iso = new Date(2026, 2, 14, 19, 30).toISOString()
    expect(toLocalInput(iso)).toBe('2026-03-14T19:30')
    expect(fromLocalInput('2026-03-14T19:30')).toBe(iso)
  })

  it('treats empty as no time', () => {
    expect(toLocalInput(null)).toBe('')
    expect(fromLocalInput('')).toBe(null)
  })

  it('keeps the saved seconds when the minute was not changed', () => {
    const saved = new Date(2026, 2, 14, 19, 30, 42).toISOString()
    expect(keepSeconds(saved, fromLocalInput('2026-03-14T19:30'))).toBe(saved)
    expect(keepSeconds(saved, fromLocalInput('2026-03-14T19:31'))).toBe(fromLocalInput('2026-03-14T19:31'))
    expect(keepSeconds(saved, null)).toBe(null)
    expect(keepSeconds(null, saved)).toBe(saved)
  })
})

describe('run lengths', () => {
  const start = '2026-03-14T19:30:00Z'

  it('measures from the start to the end, or to now while running', () => {
    expect(secondsBetween(start, '2026-03-14T21:45:30Z')).toBe(8130)
    expect(secondsBetween(start, null, Date.parse('2026-03-14T19:31:00Z'))).toBe(60)
    expect(secondsBetween(null, '2026-03-14T21:45:30Z')).toBe(null)
  })

  it('says how late or early the run went up', () => {
    expect(minutesLate(start, '2026-03-14T19:34:10Z')).toBe(4)
    expect(minutesLate(start, '2026-03-14T19:28:00Z')).toBe(-2)
    expect(minutesLate(start, null)).toBe(null)
    expect(formatLateness(4)).toBe('+4 min')
    expect(formatLateness(-2)).toBe('−2 min')
    expect(formatLateness(0)).toBe('on time')
    expect(formatLateness(null)).toBe('')
  })
})
