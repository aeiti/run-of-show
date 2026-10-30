import { getToken, socketUrl } from './api'

// Close codes from backend/shows/consumers.py.
const NOT_SIGNED_IN = 4401
const NO_ACCESS = 4403
const NOT_FOUND = 4404

/**
 * Follow a production's live updates (backend/shows/live.py). Reconnects
 * with backoff when the connection drops, and calls onResync after each
 * reconnect, since anything sent while it was down is lost.
 *
 * - onMessage(message): a change to apply ({ type: 'run.event' | 'cues' | … })
 * - onStatus('connecting' | 'live' | 'reconnecting')
 * - onResync(): refetch everything
 * - onGone(): access lost or the production deleted; stop following
 * - onSignedOut(): the token no longer works
 *
 * Returns a function that stops following.
 */
export function follow(productionId, { onMessage, onStatus, onResync, onGone, onSignedOut }) {
  let socket = null
  let stopped = false
  let attempts = 0
  let timer = null
  let everReady = false
  // A password change replaces the token and closes this socket with 4401;
  // one retry picks up the new token before treating it as signed out.
  let signedOutOnce = false

  function connect() {
    onStatus(everReady ? 'reconnecting' : 'connecting')
    socket = new WebSocket(socketUrl(`/ws/productions/${productionId}/`))
    socket.onopen = () => socket.send(JSON.stringify({ type: 'auth', token: getToken() }))
    socket.onmessage = (e) => {
      const message = JSON.parse(e.data)
      if (message.type === 'ready') {
        attempts = 0
        signedOutOnce = false
        onStatus('live')
        if (everReady) onResync()
        everReady = true
        return
      }
      onMessage(message)
    }
    socket.onclose = (e) => {
      if (stopped) return
      if (e.code === NO_ACCESS || e.code === NOT_FOUND) {
        stopped = true
        onGone()
        return
      }
      if (e.code === NOT_SIGNED_IN) {
        if (signedOutOnce || !getToken()) {
          stopped = true
          onSignedOut()
          return
        }
        signedOutOnce = true
      }
      // 1s, 2s, 4s … up to 15s between attempts.
      const delay = Math.min(15000, 1000 * 2 ** attempts++)
      onStatus('reconnecting')
      timer = setTimeout(connect, delay)
    }
  }

  connect()
  return () => {
    stopped = true
    clearTimeout(timer)
    socket?.close()
  }
}
