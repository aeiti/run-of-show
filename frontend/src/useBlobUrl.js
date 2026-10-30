import { useEffect, useState } from 'react'

/**
 * An object URL for a private file, for an <img> or <iframe> (which can't
 * send the auth header themselves), and the error if it couldn't be fetched.
 * ``load`` fetches the blob; it runs again whenever ``key`` changes, and
 * nothing is fetched while ``key`` is null. The URL is revoked when the key
 * changes or the component unmounts.
 */
export function useBlobUrl(load, key) {
  const [state, setState] = useState({ url: null, error: '' })

  useEffect(() => {
    if (key == null) return
    let cancelled = false
    let created = null
    load()
      .then((blob) => {
        if (cancelled) return
        created = URL.createObjectURL(blob)
        setState({ url: created, error: '' })
      })
      .catch((e) => !cancelled && setState({ url: null, error: e.message }))
    return () => {
      cancelled = true
      if (created) URL.revokeObjectURL(created)
      setState({ url: null, error: '' })
    }
    // load is a new function every render; key says when it means something new.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key])

  return state
}
