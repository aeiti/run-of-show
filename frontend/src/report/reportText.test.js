import { describe, expect, it } from 'vitest'
import { cueText, lateness, length, noteMoment, noteWhere, parseAddresses, sceneName } from './reportText'

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
