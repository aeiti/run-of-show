import { useEffect, useState } from 'react'
import { api } from '../api'
import { can, MEMBER_ROLES, ROLES } from '../access'

const nameOf = (user) => user.display_name || user.username

/**
 * Who is on the production and in what role. Owners and stage managers can
 * add people (by username or email), change roles and remove them; any
 * member can leave.
 */
export default function PeopleDialog({ production, me, onClose, onLeft }) {
  const [people, setPeople] = useState(null)
  const [invite, setInvite] = useState({ user: '', role: 'viewer' })
  const [confirmRemove, setConfirmRemove] = useState(null)
  const [error, setError] = useState('')
  const sharing = can(production.role, 'share')

  useEffect(() => {
    api.members(production.id).then(setPeople).catch((e) => setError(e.message))
  }, [production.id])

  const setMembers = (fn) => setPeople((prev) => ({ ...prev, members: fn(prev.members) }))

  async function run(fn) {
    setError('')
    try {
      await fn()
    } catch (err) {
      setError(err.message)
    }
  }

  const add = (e) => {
    e.preventDefault()
    run(async () => {
      const added = await api.addMember(production.id, invite.user.trim(), invite.role)
      setMembers((members) => [...members, added])
      setInvite({ user: '', role: invite.role })
    })
  }

  const changeRole = (membership, role) =>
    run(async () => {
      const updated = await api.updateMember(membership.id, role)
      setMembers((members) => members.map((m) => (m.id === updated.id ? updated : m)))
    })

  const remove = (membership) => {
    if (confirmRemove !== membership.id) {
      setConfirmRemove(membership.id)
      return
    }
    run(async () => {
      await api.removeMember(membership.id)
      setConfirmRemove(null)
      if (membership.user.id === me?.id) onLeft()
      else setMembers((members) => members.filter((m) => m.id !== membership.id))
    })
  }

  return (
    <div className="dialog-backdrop" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="dialog people panel" role="dialog" aria-modal="true" aria-labelledby="people-title">
        <div className="row-between">
          <h2 id="people-title">People</h2>
          <button className="ghost small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted small-print">
          Stage managers can edit the cue list and share the production. Operators run the show. Viewers follow along.
          Only the owner can delete it.
        </p>

        {people && (
          <ul className="people-list">
            <li>
              <span className="person">{nameOf(people.owner)}</span>
              <span className="muted">{ROLES.owner}</span>
            </li>
            {people.members.map((m) => {
              const self = m.user.id === me?.id
              return (
                <li key={m.id}>
                  <span className="person">
                    {nameOf(m.user)}
                    {self && <span className="muted"> (you)</span>}
                  </span>
                  {sharing ? (
                    <select
                      aria-label={`Role for ${nameOf(m.user)}`}
                      value={m.role}
                      onChange={(e) => changeRole(m, e.target.value)}
                    >
                      {MEMBER_ROLES.map((r) => (
                        <option key={r} value={r}>
                          {ROLES[r]}
                        </option>
                      ))}
                    </select>
                  ) : (
                    <span className="muted">{ROLES[m.role]}</span>
                  )}
                  {(sharing || self) && (
                    <button
                      className={`ghost small ${confirmRemove === m.id ? 'danger' : ''}`}
                      onClick={() => remove(m)}
                      onBlur={() => setConfirmRemove(null)}
                    >
                      {confirmRemove === m.id ? 'Confirm' : self ? 'Leave' : 'Remove'}
                    </button>
                  )}
                </li>
              )
            })}
          </ul>
        )}

        {sharing && (
          <form className="row invite" onSubmit={add}>
            <input
              required
              aria-label="Username or email"
              placeholder="Username or email"
              value={invite.user}
              onChange={(e) => setInvite({ ...invite, user: e.target.value })}
            />
            <select aria-label="Role" value={invite.role} onChange={(e) => setInvite({ ...invite, role: e.target.value })}>
              {MEMBER_ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLES[r]}
                </option>
              ))}
            </select>
            <button type="submit">Add</button>
          </form>
        )}
        {error && <p className="error">{error}</p>}
      </section>
    </div>
  )
}
