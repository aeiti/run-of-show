import { Link } from 'react-router'

/**
 * Shown in place of a board or follow view this account can't open: the
 * production doesn't exist, was deleted, or this account isn't a member.
 * The server answers all three the same way, so this can't tell them apart.
 */
export default function Unavailable({ me }) {
  return (
    <main className="unavailable panel">
      <h2>Can’t open this production</h2>
      <p>
        It doesn’t exist, it was deleted, or {me ? <strong>{me.username}</strong> : 'this account'} isn’t a member of
        it. Ask the production’s owner or stage manager to add you under People, or sign in as someone who is.
      </p>
      <Link className="button ghost" to="/">
        ← Productions
      </Link>
    </main>
  )
}
