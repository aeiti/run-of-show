import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { follow } from './live'
import { defaultApiUrl, socketUrl } from './api'

// A stand-in for the browser's WebSocket that the test drives by hand.
class FakeSocket {
  static all = []
  constructor(url) {
    this.url = url
    this.sent = []
    FakeSocket.all.push(this)
  }
  send(data) {
    this.sent.push(JSON.parse(data))
  }
  close() {
    this.closed = true
  }
  open() {
    this.onopen()
  }
  receive(message) {
    this.onmessage({ data: JSON.stringify(message) })
  }
  drop(code = 1006) {
    this.onclose({ code })
  }
}

let token
beforeEach(() => {
  FakeSocket.all = []
  token = 'tok-1'
  vi.useFakeTimers()
  vi.stubGlobal('WebSocket', FakeSocket)
  vi.stubGlobal('localStorage', { getItem: () => token, removeItem: () => {} })
})
afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function start() {
  const calls = { messages: [], statuses: [], resyncs: 0, gone: 0, signedOut: 0 }
  const stop = follow(7, {
    onMessage: (m) => calls.messages.push(m),
    onStatus: (s) => calls.statuses.push(s),
    onResync: () => calls.resyncs++,
    onGone: () => calls.gone++,
    onSignedOut: () => calls.signedOut++,
  })
  return { calls, stop, socket: () => FakeSocket.all.at(-1) }
}

describe('follow', () => {
  it('authenticates first, then passes messages on', () => {
    const { calls, socket } = start()
    socket().open()
    expect(socket().url).toMatch(/\/ws\/productions\/7\/$/)
    expect(socket().sent).toEqual([{ type: 'auth', token: 'tok-1' }])
    socket().receive({ type: 'ready', role: 'owner' })
    socket().receive({ type: 'cues' })
    expect(calls.statuses).toEqual(['connecting', 'live'])
    expect(calls.messages).toEqual([{ type: 'cues' }])
    expect(calls.resyncs).toBe(0)
  })

  it('reconnects with backoff and resyncs once it is back', () => {
    const { calls, socket } = start()
    socket().open()
    socket().receive({ type: 'ready' })
    socket().drop()
    expect(calls.statuses.at(-1)).toBe('reconnecting')
    vi.advanceTimersByTime(999)
    expect(FakeSocket.all).toHaveLength(1)
    vi.advanceTimersByTime(1)
    expect(FakeSocket.all).toHaveLength(2)
    socket().drop()
    vi.advanceTimersByTime(1999)
    expect(FakeSocket.all).toHaveLength(2) // the second wait is longer
    vi.advanceTimersByTime(1)
    socket().open()
    socket().receive({ type: 'ready' })
    expect(calls.resyncs).toBe(1)
    expect(calls.statuses.at(-1)).toBe('live')
  })

  it('retries once with a new token before giving up on sign-in', () => {
    const { calls, socket } = start()
    socket().open()
    socket().receive({ type: 'ready' })
    token = 'tok-2' // a password change replaced it
    socket().drop(4401)
    vi.advanceTimersByTime(1000)
    socket().open()
    expect(socket().sent).toEqual([{ type: 'auth', token: 'tok-2' }])
    expect(calls.signedOut).toBe(0)
    socket().drop(4401)
    expect(calls.signedOut).toBe(1)
    vi.advanceTimersByTime(60000)
    expect(FakeSocket.all).toHaveLength(2)
  })

  it('stops for good when access is lost or the production is gone', () => {
    for (const code of [4403, 4404]) {
      const { calls, socket } = start()
      socket().drop(code)
      vi.advanceTimersByTime(60000)
      expect(calls.gone).toBe(1)
      expect(FakeSocket.all.filter((s) => !s.closed)).toHaveLength(1)
      FakeSocket.all = []
    }
  })

  it('stops reconnecting once unsubscribed', () => {
    const { socket, stop } = start()
    stop()
    expect(socket().closed).toBe(true)
    socket().drop()
    vi.advanceTimersByTime(60000)
    expect(FakeSocket.all).toHaveLength(1)
  })
})

describe('socketUrl', () => {
  it('puts the path on the API host with a ws scheme', () => {
    expect(socketUrl('/ws/productions/3/')).toBe('ws://localhost:5600/ws/productions/3/')
  })
})

describe('defaultApiUrl', () => {
  it('uses the host the board was loaded from, so other machines reach this one', () => {
    expect(defaultApiUrl({ protocol: 'http:', hostname: '192.168.1.241' })).toBe('http://192.168.1.241:5600/api')
    expect(defaultApiUrl({ protocol: 'http:', hostname: 'adams-macbook-pro.local' })).toBe(
      'http://adams-macbook-pro.local:5600/api',
    )
  })

  it('keeps https, and falls back to localhost outside a browser', () => {
    expect(defaultApiUrl({ protocol: 'https:', hostname: 'show.example' })).toBe('https://show.example:5600/api')
    expect(defaultApiUrl(undefined)).toBe('http://localhost:5600/api')
  })
})
