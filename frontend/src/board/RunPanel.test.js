import { describe, expect, it } from 'vitest'
import { logItems } from './RunPanel'

describe('logItems', () => {
  it('lists newest first', () => {
    const events = [{ id: 1, fired_at: '2026-10-31T05:12:52.100Z' }]
    const notes = [{ id: 1, created_at: '2026-10-31T05:12:52.300Z' }]
    const consoleEvents = [{ id: 1, at: '2026-10-31T05:12:52.200Z' }]
    expect(logItems(events, notes, consoleEvents).map((x) => x.key)).toEqual(['n1', 'c1', 'e1'])
  })

  it('puts the later of two entries in the same instant on top', () => {
    const at = '2026-10-31T05:12:52.481Z'
    const events = [
      { id: 7, fired_at: at },
      { id: 8, fired_at: at },
    ]
    const consoleEvents = [
      { id: 3, at },
      { id: 4, at },
    ]
    const keys = logItems(events, [], consoleEvents).map((x) => x.key)
    expect(keys.indexOf('e8')).toBeLessThan(keys.indexOf('e7'))
    expect(keys.indexOf('c4')).toBeLessThan(keys.indexOf('c3'))
  })
})
