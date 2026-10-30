import { useEffect, useState } from 'react'
import { api } from '../api'

const blank = { username: '', email: '', display_name: '', password: '', is_admin: false }

/**
 * User management for admins: add, edit, suspend, reactivate and delete
 * accounts. Suspending keeps an account's productions and history; deleting
 * is refused while they own any.
 */
export default function Users({ me }) {
  const [users, setUsers] = useState(null)
  const [query, setQuery] = useState('')
  const [editing, setEditing] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [status, setStatus] = useState('')
  const [error, setError] = useState('')

  useEffect(() => {
    // Debounced so typing in the search box doesn't send a request per key.
    const timer = setTimeout(() => {
      api.users(query).then(setUsers).catch((e) => setError(e.message))
    }, 200)
    return () => clearTimeout(timer)
  }, [query])

  const replace = (updated) => setUsers((prev) => prev.map((u) => (u.id === updated.id ? updated : u)))

  async function run(fn, done = '') {
    setError('')
    setStatus('')
    try {
      await fn()
      setStatus(done)
      return true
    } catch (err) {
      setError(err.message)
      return false
    }
  }

  const setActive = (user, is_active) =>
    run(async () => replace(await api.updateUser(user.id, { is_active })), is_active ? '' : `${user.username} is suspended and signed out.`)

  const sendReset = (user) => run(() => api.sendPasswordReset(user.id), `Reset link sent to ${user.email}.`)

  const remove = (user) => {
    if (confirmDelete !== user.id) {
      setConfirmDelete(user.id)
      return
    }
    setConfirmDelete(null)
    run(async () => {
      await api.deleteUser(user.id)
      setUsers((prev) => prev.filter((u) => u.id !== user.id))
    }, `${user.username} deleted.`)
  }

  return (
    <main className="users">
      <section className="panel">
        <h2>Users</h2>
        <label className="users-search">
          <input
            type="search"
            aria-label="Search users"
            placeholder="Search by username, name or email"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
        {status && <p className="ok">{status}</p>}
        {error && <p className="error">{error}</p>}
        <div className="table-scroll">
          <table className="users-table">
            <thead>
              <tr>
                <th>User</th>
                <th>Email</th>
                <th>Productions</th>
                <th>Last sign-in</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {users?.length === 0 && (
                <tr>
                  <td colSpan={5} className="muted">
                    No users match.
                  </td>
                </tr>
              )}
              {users?.map((u) => {
                const self = u.id === me.id
                return [
                  <tr key={u.id} className={u.is_active ? '' : 'suspended'}>
                    <td>
                      {u.username}
                      {u.is_admin && <span className="badge">admin</span>}
                      {!u.is_active && <span className="badge">suspended</span>}
                      {u.display_name && <div className="muted">{u.display_name}</div>}
                    </td>
                    <td>{u.email}</td>
                    <td>{u.productions_owned}</td>
                    <td className="muted">{u.last_login ? new Date(u.last_login).toLocaleDateString() : 'never'}</td>
                    <td>
                      <div className="actions">
                        <button className="ghost small" onClick={() => setEditing(editing === u.id ? null : u.id)}>
                          {editing === u.id ? 'Close' : 'Edit'}
                        </button>
                        {!self &&
                          (u.is_active ? (
                            <button className="ghost small" onClick={() => setActive(u, false)}>
                              Suspend
                            </button>
                          ) : (
                            <button className="ghost small" onClick={() => setActive(u, true)}>
                              Reactivate
                            </button>
                          ))}
                        {u.is_active && u.email && (
                          <button className="ghost small" onClick={() => sendReset(u)}>
                            Send reset
                          </button>
                        )}
                        {!self && (
                          <button
                            className="ghost small danger"
                            onClick={() => remove(u)}
                            onBlur={() => setConfirmDelete(null)}
                            title={u.productions_owned ? 'Owns productions: suspend instead' : undefined}
                          >
                            {confirmDelete === u.id ? 'Confirm delete' : 'Delete'}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>,
                  editing === u.id && (
                    <tr key={`edit-${u.id}`} className="edit-row">
                      <td colSpan={5}>
                        <UserForm
                          user={u}
                          self={self}
                          onSubmit={async (data) => {
                            if (await run(async () => replace(await api.updateUser(u.id, data)), 'Saved.')) setEditing(null)
                          }}
                        />
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>New user</h2>
        <UserForm
          onSubmit={(data) =>
            run(async () => {
              const created = await api.createUser(data)
              setUsers((prev) => [...prev, created].sort((a, b) => a.username.localeCompare(b.username)))
            }, `${data.username} created.`)
          }
        />
      </section>
    </main>
  )
}

/** Create a user (no ``user``) or edit one. A blank password leaves it unchanged. */
function UserForm({ user, self, onSubmit }) {
  const [form, setForm] = useState(
    user ? { ...blank, username: user.username, email: user.email, display_name: user.display_name, is_admin: user.is_admin } : blank,
  )
  const field = (key) => ({ value: form[key], onChange: (e) => setForm({ ...form, [key]: e.target.value }) })

  async function submit(e) {
    e.preventDefault()
    const data = { ...form }
    if (user && !data.password) delete data.password
    // A new-user form clears once the account is created.
    if ((await onSubmit(data)) && !user) setForm(blank)
  }

  return (
    <form onSubmit={submit} className={user ? 'field-grid' : ''}>
      <label>
        Username
        <input required autoComplete="off" {...field('username')} />
      </label>
      <label>
        Email
        <input required type="email" autoComplete="off" {...field('email')} />
      </label>
      <label>
        Display name
        <input autoComplete="off" {...field('display_name')} />
      </label>
      <label>
        {user ? 'New password (leave blank to keep)' : 'Password'}
        <input required={!user} type="password" autoComplete="new-password" {...field('password')} />
      </label>
      <label className="check">
        <input
          type="checkbox"
          checked={form.is_admin}
          disabled={self}
          onChange={(e) => setForm({ ...form, is_admin: e.target.checked })}
        />
        Admin: can manage users{self && ' (you can’t remove your own)'}
      </label>
      <div className="row">
        <button type="submit">{user ? 'Save' : 'Create'}</button>
      </div>
    </form>
  )
}
