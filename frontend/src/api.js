const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'
const TOKEN_KEY = 'ros-token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)

// The live-update socket for a path such as /ws/productions/3/, on the API's
// host: http://localhost:8000/api becomes ws://localhost:8000/ws/productions/3/.
export function socketUrl(path) {
  const url = new URL(BASE, globalThis.location?.href)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  url.pathname = url.pathname.replace(/\/api\/?$/, '') + path
  return url.toString()
}
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

async function request(path, { method = 'GET', body, raw = false, token = getToken() } = {}) {
  // FormData (file uploads) sets its own multipart Content-Type.
  const form = body instanceof FormData
  const headers = form ? {} : { 'Content-Type': 'application/json' }
  if (token) headers.Authorization = `Token ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: form ? body : body ? JSON.stringify(body) : undefined,
  })
  if (res.status === 401) clearToken()
  if (!res.ok) {
    const text = await res.text()
    let data = null
    try {
      data = JSON.parse(text)
    } catch {
      // Not JSON (e.g. an HTML error page); keep the raw text in the message.
    }
    throw new ApiError(res.status, data, data ? flatten(data) : `${method} ${path} → ${res.status} ${text}`)
  }
  if (raw) return res
  return res.status === 204 ? null : res.json()
}

// Downloads need the auth header, so fetch the file and hand the browser a blob.
async function download(path) {
  const res = await request(path, { raw: true })
  const name = /filename="([^"]+)"/.exec(res.headers.get('Content-Disposition') ?? '')?.[1] ?? 'export.csv'
  const url = URL.createObjectURL(await res.blob())
  const a = Object.assign(document.createElement('a'), { href: url, download: name })
  a.click()
  URL.revokeObjectURL(url)
}

export class ApiError extends Error {
  constructor(status, data, message) {
    super(message)
    this.status = status
    this.data = data
  }
}

// DRF errors look like {"detail": "..."} or {"number": ["Cue 12 already exists."]}.
function flatten(data) {
  if (typeof data === 'string') return data
  if (Array.isArray(data)) return data.map(flatten).join(' ')
  return Object.entries(data)
    .map(([key, value]) => (key === 'detail' || key === 'non_field_errors' ? flatten(value) : `${key}: ${flatten(value)}`))
    .join(' ')
}

const setToken = ({ token }) => localStorage.setItem(TOKEN_KEY, token)

export async function login(username, password) {
  setToken(await request('/auth/token/', { method: 'POST', body: { username, password } }))
}

// body: { username, email, password, display_name }
export async function signup(body) {
  setToken(await request('/auth/signup/', { method: 'POST', body }))
}

// Forget the token locally first, so a reload mid-request can't leave it behind.
export async function logout() {
  const token = getToken()
  clearToken()
  await request('/auth/logout/', { method: 'POST', token }).catch(() => {})
}

// Changing the password replaces the token (signing out other devices), so keep the new one.
export async function changePassword(current_password, new_password) {
  setToken(await request('/auth/password/', { method: 'POST', body: { current_password, new_password } }))
}

export const api = {
  me: () => request('/auth/me/'),
  updateMe: (data) => request('/auth/me/', { method: 'PATCH', body: data }),
  requestPasswordReset: (email) => request('/auth/password-reset/', { method: 'POST', body: { email } }),
  confirmPasswordReset: (uid, token, new_password) =>
    request('/auth/password-reset/confirm/', { method: 'POST', body: { uid, token, new_password } }),
  productions: () => request('/productions/'),
  createProduction: (data) => request('/productions/', { method: 'POST', body: data }),
  production: (id) => request(`/productions/${id}/`),
  updateProduction: (id, data) => request(`/productions/${id}/`, { method: 'PATCH', body: data }),
  deleteProduction: (id) => request(`/productions/${id}/`, { method: 'DELETE' }),
  // A copy with the cue list but no runs; data overrides the copy's details.
  duplicateProduction: (id, data = {}) => request(`/productions/${id}/duplicate/`, { method: 'POST', body: data }),
  exportProduction: (id) => download(`/productions/${id}/export/`),
  // form is FormData with the exported JSON as file; always creates a new production.
  importProduction: (form) => request('/productions/import/', { method: 'POST', body: form }),
  cues: (id) => request(`/productions/${id}/cues/`),
  createCue: (id, data) => request(`/productions/${id}/cues/`, { method: 'POST', body: data }),
  updateCue: (cueId, data) => request(`/cues/${cueId}/`, { method: 'PATCH', body: data }),
  deleteCue: (cueId) => request(`/cues/${cueId}/`, { method: 'DELETE' }),
  // { owner, members: [{ id, user, role }] }
  members: (id) => request(`/productions/${id}/members/`),
  // user is a username or email.
  addMember: (id, user, role) => request(`/productions/${id}/members/`, { method: 'POST', body: { user, role } }),
  updateMember: (membershipId, role) => request(`/memberships/${membershipId}/`, { method: 'PATCH', body: { role } }),
  removeMember: (membershipId) => request(`/memberships/${membershipId}/`, { method: 'DELETE' }),
  runs: (id) => request(`/productions/${id}/runs/`),
  createRun: (id, data) => request(`/productions/${id}/runs/`, { method: 'POST', body: data }),
  run: (runId) => request(`/runs/${runId}/`),
  // Operator actions return { event, state }.
  go: (runId, cue) => request(`/runs/${runId}/go/`, { method: 'POST', body: cue ? { cue } : {} }),
  back: (runId) => request(`/runs/${runId}/back/`, { method: 'POST' }),
  goto: (runId, cue) => request(`/runs/${runId}/goto/`, { method: 'POST', body: { cue } }),
  reset: (runId) => request(`/runs/${runId}/reset/`, { method: 'POST' }),
  hold: (runId, reason) => request(`/runs/${runId}/hold/`, { method: 'POST', body: { reason } }),
  resume: (runId) => request(`/runs/${runId}/resume/`, { method: 'POST' }),
  // Notes on cues within a run: data is { cue, text } to add, { text } to edit.
  addCueNote: (runId, data) => request(`/runs/${runId}/notes/`, { method: 'POST', body: data }),
  updateCueNote: (noteId, data) => request(`/cue-notes/${noteId}/`, { method: 'PATCH', body: data }),
  deleteCueNote: (noteId) => request(`/cue-notes/${noteId}/`, { method: 'DELETE' }),
  endRun: (runId) => request(`/runs/${runId}/end/`, { method: 'POST' }),
  // body is FormData with file or text, mode, list and dry_run.
  importCues: (id, form) => request(`/productions/${id}/cues/import/`, { method: 'POST', body: form }),
  exportCues: (id) => download(`/productions/${id}/cues/export/`),
  exportRun: (runId) => download(`/runs/${runId}/export/`),
  // Admin only.
  users: (q = '') => request(`/admin/users/${q ? `?q=${encodeURIComponent(q)}` : ''}`),
  createUser: (data) => request('/admin/users/', { method: 'POST', body: data }),
  updateUser: (id, data) => request(`/admin/users/${id}/`, { method: 'PATCH', body: data }),
  deleteUser: (id) => request(`/admin/users/${id}/`, { method: 'DELETE' }),
  sendPasswordReset: (id) => request(`/admin/users/${id}/send-reset/`, { method: 'POST' }),
}
