const LOCAL = ['localhost', '127.0.0.1', '[::1]']

/** True when the board was opened by a name only this computer understands. */
export const isLocalHost = (hostname) => LOCAL.includes(hostname)

/**
 * The addresses to give someone for `path`. Opened on localhost, a link from
 * the address bar only works on this computer, so use the names this machine
 * has on the network (LAN_HOSTS, from the API) on the same port. With none,
 * or when the board was already opened by a network name, it's the address
 * the board is on.
 */
export function shareUrls(path, lanHosts = [], location = globalThis.location) {
  if (!isLocalHost(location.hostname) || lanHosts.length === 0) return [`${location.origin}${path}`]
  const port = location.port ? `:${location.port}` : ''
  return lanHosts.map((host) => {
    const name = host.includes(':') && !host.startsWith('[') ? `[${host}]` : host
    return `${location.protocol}//${name}${port}${path}`
  })
}
