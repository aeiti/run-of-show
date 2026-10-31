import { useState } from 'react'
import { Link } from 'react-router'

const LOCAL = ['localhost', '127.0.0.1', '[::1]']

/** The follow view link, plus its full address to hand to someone else. */
export default function FollowShare({ productionId }) {
  const [open, setOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const path = `/productions/${productionId}/follow`
  const url = `${window.location.origin}${path}`
  // The clipboard API needs a secure context, which a plain-http LAN address isn't.
  const canCopy = Boolean(navigator.clipboard && window.isSecureContext)

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      setCopied(false)
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
        onClick={() => setOpen(!open)}
      >
        Link
      </button>
      {open && (
        <div className="follow-share-box">
          <div className="row">
            <input readOnly aria-label="Follow view address" value={url} autoFocus onFocus={(e) => e.target.select()} />
            {canCopy && (
              <button className="small" onClick={copy}>
                {copied ? 'Copied' : 'Copy'}
              </button>
            )}
          </div>
          {LOCAL.includes(window.location.hostname) && (
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
