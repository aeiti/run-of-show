import { describe, expect, it } from 'vitest'
import { isLocalHost, shareUrls } from './shareUrls'

const at = (href) => new URL(href)
const PATH = '/productions/3/follow'

describe('shareUrls', () => {
  it('swaps localhost for the network names, on the same port', () => {
    expect(shareUrls(PATH, ['adams-macbook-pro.local', '192.168.1.241'], at('http://localhost:3200/productions/3'))).toEqual([
      'http://adams-macbook-pro.local:3200/productions/3/follow',
      'http://192.168.1.241:3200/productions/3/follow',
    ])
  })

  it('does the same for 127.0.0.1 and [::1]', () => {
    expect(shareUrls(PATH, ['192.168.1.241'], at('http://127.0.0.1:5176/'))).toEqual([
      'http://192.168.1.241:5176/productions/3/follow',
    ])
    expect(shareUrls(PATH, ['192.168.1.241'], at('http://[::1]:3200/'))).toEqual([
      'http://192.168.1.241:3200/productions/3/follow',
    ])
  })

  it('falls back to the current address with no network names', () => {
    expect(shareUrls(PATH, [], at('http://localhost:3200/'))).toEqual(['http://localhost:3200/productions/3/follow'])
  })

  it('keeps the current address when the board was opened from the network', () => {
    expect(shareUrls(PATH, ['adams-macbook-pro.local'], at('http://192.168.1.241:3200/'))).toEqual([
      'http://192.168.1.241:3200/productions/3/follow',
    ])
  })

  it('brackets an IPv6 address and leaves out a default port', () => {
    expect(shareUrls(PATH, ['fd00::5'], at('https://localhost/'))).toEqual(['https://[fd00::5]/productions/3/follow'])
  })
})

describe('isLocalHost', () => {
  it('knows the loopback names', () => {
    expect(['localhost', '127.0.0.1', '[::1]'].every(isLocalHost)).toBe(true)
    expect(isLocalHost('192.168.1.241')).toBe(false)
  })
})
