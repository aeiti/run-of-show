import { describe, expect, it } from 'vitest'
import { nearestScrollTop } from './scroll'

// A list 300px tall, 100px down the page, scrolled 500px; card positions are on the page.
const list = { scrollTop: 500, clientHeight: 300, getBoundingClientRect: () => ({ top: 100 }) }
const card = (top, height = 40) => ({ getBoundingClientRect: () => ({ top, bottom: top + height }) })

describe('nearestScrollTop', () => {
  it('leaves a card in full view where it is', () => {
    expect(nearestScrollTop(list, card(100))).toBeNull()
    expect(nearestScrollTop(list, card(360))).toBeNull()
  })

  it('brings a card below the list up to its bottom edge', () => {
    // Bottom at 420 on the page is 320 into the list: 20px too far.
    expect(nearestScrollTop(list, card(380))).toBe(520)
  })

  it('brings a card above the list down to its top edge', () => {
    expect(nearestScrollTop(list, card(70))).toBe(470)
  })

  it('brings the cue after it into view as well', () => {
    // The card is in view, but the one after ends at 440: 40px below the list.
    expect(nearestScrollTop(list, card(340), card(400))).toBe(540)
    expect(nearestScrollTop(list, card(300), card(340))).toBeNull()
  })

  it('keeps the card itself in view when both will not fit', () => {
    // Showing all of the next one would scroll the card's top (60px down) out of view.
    expect(nearestScrollTop(list, card(160, 280), card(440, 200))).toBe(560)
  })
})
