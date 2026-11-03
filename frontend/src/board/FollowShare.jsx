import { useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api'
import { isLocalHost, shareUrls } from './shareUrls'

/** The follow view link, plus its full address to hand to someone else. */
export default function FollowShare({ productionId }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(null)
  // This machine's network names, asked for the first time the box opens on localhost.
  const [lanHosts, setLanHosts] = useState(null)
  const path = `/productions/${productionId}/follow`
  const local = isLocalHost(window.location.hostname)
  const urls = shareUrls(path, lanHosts ?? [])
  // The clipboard API needs a secure context, which a plain-http LAN address isn't.
  const canCopy = Boolean(navigator.clipboard && window.isSecureContext)

  function toggle() {
    setOpen(!open)
    if (!open && local && lanHosts === null) {
      api
        .network()
        .then((data) => setLanHosts(data.hosts))
        .catch(() => setLanHosts([]))
    }
  }

  async function copy(url) {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(url)
      setTimeout(() => setCopied(null), 2000)
    } catch {
      setCopied(null)
    }
  }

  return (
    <div className="follow-share">
      <Link className="button ghost small" to={path} title="A read-only view of the live run, for tablets backstage">
        Follow view
      </Link>
      <button
        className="ghost small"
        aria-expanded={open}
        title="Show the follow view's address to give someone"
        onClick={toggle}
      >
        Link
      </button>
      {open && (
        <div className="follow-share-box">
          {urls.map((url, i) => (
            <div className="row" key={url}>
              <input
                readOnly
                aria-label="Follow view address"
                value={url}
                autoFocus={i === 0}
                onFocus={(e) => e.target.select()}
              />
              {canCopy && (
                <button className="small" onClick={() => copy(url)}>
                  {copied === url ? 'Copied' : 'Copy'}
                </button>
              )}
            </div>
          ))}
          {local && lanHosts?.length === 0 && (
            <p className="muted">
              This address only works on this computer. To share it, open the board from this computer&apos;s network
              address (see <code>LAN_HOSTS</code> in the README).
            </p>
          )}
        </div>
      )}
    </div>
  )
}
