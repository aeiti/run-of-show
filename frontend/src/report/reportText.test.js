import { describe, expect, it } from 'vitest'
import {
  formatCallTemplate,
  parseCallTemplate,
  actClock,
  actName,
  bySection,
  cueText,
  daySections,
  lateness,
  length,
  noteMoment,
  noteWhere,
  GENERAL,
  parseAddresses,
  sceneName,
  timeline,
} from './reportText'

describe('length', () => {
  it('writes seconds as a clock, and a missing length as a dash', () => {
    expect(length(3360)).toBe('56:00')
    expect(length(3723)).toBe('1:02:03')
    expect(length(0)).toBe('0:00')
    expect(length(null)).toBe('–')
    expect(length(undefined)).toBe('–')
  })
})

describe('lateness', () => {
  it('says how late or early, and calls under a minute on time', () => {
    expect(lateness(240)).toBe('4:00 late')
    expect(lateness(-120)).toBe('2:00 early')
    expect(lateness(59)).toBe('on time')
    expect(lateness(-59)).toBe('on time')
    expect(lateness(null)).toBe('')
  })
})

describe('names', () => {
  it('names the cues before the first scene', () => {
    expect(sceneName({ name: '1.1 The Lamp Room' })).toBe('1.1 The Lamp Room')
    expect(sceneName({ name: '' })).toBe('Before the first scene')
  })

  it('writes a cue as its number and label', () => {
    expect(cueText('12', 'Lightning')).toBe('Q12 Lightning')
    expect(cueText('12')).toBe('Q12')
    expect(cueText(null)).toBe('')
  })
})

describe('parseAddresses', () => {
  it('splits on commas, semicolons, spaces and new lines', () => {
    expect(parseAddresses('sm@example.com, lx@example.com;sound@example.com\nfly@example.com  ')).toEqual([
      'sm@example.com',
      'lx@example.com',
      'sound@example.com',
      'fly@example.com',
    ])
  })

  it('drops repeats, ignoring case, and keeps the first spelling', () => {
    expect(parseAddresses('SM@example.com sm@example.com')).toEqual(['SM@example.com'])
  })

  it('gives nothing for an empty box', () => {
    expect(parseAddresses('  ,, ')).toEqual([])
  })
})

describe('performance notes', () => {
  it('says where the show was: the cue and scene, either, or neither', () => {
    expect(noteWhere({ cue_number: '12', cue_label: 'Bell', scene: '1.2 Wreck' })).toBe('Q12 Bell · 1.2 Wreck')
    expect(noteWhere({ cue_number: null, cue_label: '', scene: '1.2 Wreck' })).toBe('1.2 Wreck')
    expect(noteWhere({ cue_number: '5', cue_label: '', scene: '' })).toBe('Q5')
    expect(noteWhere({ cue_number: null, cue_label: '', scene: '' })).toBe('')
  })

  it('puts a typed time on the day of the run, after midnight when it must be', () => {
    const start = new Date(2026, 2, 14, 19, 30).toISOString()
    expect(noteMoment('21:05', start)).toBe(new Date(2026, 2, 14, 21, 5).toISOString())
    // Before the start (the house), still the same day.
    expect(noteMoment('19:10', start)).toBe(new Date(2026, 2, 14, 19, 10).toISOString())
    expect(noteMoment('0:15', start)).toBe(new Date(2026, 2, 15, 0, 15).toISOString())
    expect(noteMoment('', start)).toBe(null)
    expect(noteMoment('later', start)).toBe(null)
  })
})

describe('note sections', () => {
  it('groups notes as the email does: every section, then old ones, then unsorted', () => {
    const notes = [
      { id: 1, section: 'Show' },
      { id: 2, section: '' },
      { id: 3, section: 'Props' },
      { id: 4, section: 'Show' },
    ]
    const groups = bySection(['Show', 'Lighting'], notes).map(([name, ns]) => [name, ns.map((n) => n.id)])
    expect(groups).toEqual([
      ['Show', [1, 4]],
      ['Lighting', []],
      ['Props', [3]],
      [GENERAL, [2]],
    ])
    expect(bySection(['Show'], [])).toEqual([['Show', []]])
    // Listed by the production, General takes the notes with no section in its own place.
    const listed = bySection(['General', 'Show'], notes).map(([name, ns]) => [name, ns.map((n) => n.id)])
    expect(listed).toEqual([
      ['General', [2]],
      ['Show', [1, 4]],
      ['Props', [3]],
    ])
  })
})

describe('timeline', () => {
  it('interleaves scenes, holds and notes by time, with untimed notes last', () => {
    const scenes = [{ name: 'Preshow', started_at: '2026-03-14T19:34:00Z' }]
    const holds = [{ reason: 'Medical', started_at: '2026-03-14T19:50:00Z' }]
    const notes = [
      { id: 1, at: '2026-03-14T19:50:00Z' },
      { id: 2, at: null },
      { id: 3, at: '2026-03-14T19:30:00Z' },
    ]
    expect(timeline(scenes, holds, notes).map((item) => item.key)).toEqual(['n3', 's0', 'h0', 'n1', 'n2'])
  })
})

describe('acts', () => {
  it('names acts in roman numerals, then plain numbers', () => {
    expect(actName(1)).toBe('Act I')
    expect(actName(4)).toBe('Act IV')
    expect(actName(12)).toBe('Act 12')
  })

  it('prints a time of day as the sample reports do', () => {
    expect(actClock(new Date(2026, 2, 14, 20, 7, 41).toISOString())).toBe('8:07')
    expect(actClock(new Date(2026, 2, 14, 0, 5).toISOString())).toBe('12:05')
    expect(actClock(new Date(2026, 2, 14, 12, 30).toISOString())).toBe('12:30')
    expect(actClock(null)).toBe('–')
  })
})

describe('call template', () => {
  it('reads one call per line as minutes before curtain and a label', () => {
    expect(parseCallTemplate('45 Wig prep starts\n\n 30  Half hour – House open \n')).toEqual({
      calls: [
        { minutes: 45, label: 'Wig prep starts' },
        { minutes: 30, label: 'Half hour – House open' },
      ],
      bad: [],
    })
    expect(parseCallTemplate('Half hour\n90 Crew call').bad).toEqual(['Half hour'])
  })

  it('writes calls back as the same lines', () => {
    const calls = [
      { minutes: 90, label: 'Crew call' },
      { minutes: 30, label: 'Half hour' },
    ]
    expect(formatCallTemplate(calls)).toBe('90 Crew call\n30 Half hour')
    expect(parseCallTemplate(formatCallTemplate(calls)).calls).toEqual(calls)
  })
})

describe('daySections', () => {
  it("merges each show's sections, with old sections and General after the production's", () => {
    const shows = [
      { performance_notes: [{ id: 1, section: 'Show' }, { id: 2, section: '' }] },
      { performance_notes: [{ id: 3, section: 'Props' }, { id: 4, section: 'Show' }] },
    ]
    const ids = daySections(['Show', 'Tech'], shows).map(([name, perShow]) => [name, perShow.map((ns) => ns.map((n) => n.id))])
    expect(ids).toEqual([
      ['Show', [[1], [4]]],
      ['Tech', [[], []]],
      ['Props', [[], [3]]],
      [GENERAL, [[2], []]],
    ])
  })
})
