import { describe, expect, it } from 'vitest'
import { sceneSpans, trackLabels } from './track'

const cue = (number, scene = '') => ({ number, scene })

describe('sceneSpans', () => {
  it('runs each scene until the next one starts', () => {
    const cues = [cue('0.1'), cue('1', 'PRESHOW'), cue('5'), cue('11', 'ONE'), cue('12')]
    expect(sceneSpans(cues).map(({ name, start, end }) => ({ name, start, end }))).toEqual([
      { name: 'PRESHOW', start: 1, end: 3 },
      { name: 'ONE', start: 3, end: 5 },
    ])
  })

  it('names only the scenes with room for a useful part of the name', () => {
    // 100 cues on 1000px: 10px a cue.
    const cues = Array.from({ length: 100 }, (_, i) => cue(String(i + 1)))
    cues[0].scene = '1: TWO BODIES' // 50 cues, 500px: plenty
    cues[50].scene = '2: KING COTTON' // 2 cues, 20px: not even 8 characters
    cues[52].scene = '3' // 2 cues, 20px: room for its whole one-character name
    cues[54].scene = '4: "MEXODUS"' // 46 cues
    expect(sceneSpans(cues, 1000).map((s) => s.labelled)).toEqual([true, false, true, true])
  })

  it('is empty when no cue has a scene', () => {
    expect(sceneSpans([cue('1'), cue('2')], 1000)).toEqual([])
  })
})

describe('trackLabels', () => {
  const many = Array.from({ length: 300 }, (_, i) => cue(String(i + 1)))

  it('labels every cue when there is room', () => {
    const cues = [cue('1'), cue('2'), cue('3')]
    expect(trackLabels(cues, 600).map((l) => l.index)).toEqual([0, 1, 2])
  })

  it('never overlaps labels, however many cues', () => {
    const labels = trackLabels(many, 1000)
    expect(labels.length).toBeGreaterThan(5)
    expect(labels.length).toBeLessThan(many.length)
    labels.slice(1).forEach((l, k) => expect(l.left).toBeGreaterThanOrEqual(labels[k].right))
  })

  it('keeps the first and last cue, inside the track', () => {
    const labels = trackLabels(many, 1000)
    expect(labels[0]).toMatchObject({ index: 0, left: 0 })
    const last = labels[labels.length - 1]
    expect(last.index).toBe(299)
    expect(last.right).toBeLessThanOrEqual(1000)
  })

  it('prefers scene starts over whole numbers, and whole numbers over point cues', () => {
    // Six cues on a track with room for roughly three labels.
    const cues = [cue('1'), cue('1.5'), cue('2'), cue('2.5', 'ACT 2'), cue('3.5'), cue('4')]
    expect(trackLabels(cues, 130).map((l) => cues[l.index].number)).toEqual(['1', '2.5', '4'])
    const plain = cues.map((c) => cue(c.number))
    expect(trackLabels(plain, 130).map((l) => plain[l.index].number)).toEqual(['1', '2', '4'])
  })

  it('returns nothing before the track has a width', () => {
    expect(trackLabels(many, 0)).toEqual([])
  })
})
