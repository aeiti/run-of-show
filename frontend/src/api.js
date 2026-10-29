const BASE = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'
const TOKEN_KEY = 'ros-token'

export const getToken = () => localStorage.getItem(TOKEN_KEY)
export const clearToken = () => localStorage.removeItem(TOKEN_KEY)

async function request(path, { method = 'GET', body } = {}) {
  const headers = { 'Content-Type': 'application/json' }
  const token = getToken()
  if (token) headers.Authorization = `Token ${token}`
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
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
  return res.status === 204 ? null : res.json()
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

export async function login(username, password) {
  const { token } = await request('/auth/token/', { method: 'POST', body: { username, password } })
  localStorage.setItem(TOKEN_KEY, token)
}

export const api = {
  productions: () => request('/productions/'),
  createProduction: (data) => request('/productions/', { method: 'POST', body: data }),
  production: (id) => request(`/productions/${id}/`),
  updateProduction: (id, data) => request(`/productions/${id}/`, { method: 'PATCH', body: data }),
  deleteProduction: (id) => request(`/productions/${id}/`, { method: 'DELETE' }),
  cues: (id) => request(`/productions/${id}/cues/`),
  createCue: (id, data) => request(`/productions/${id}/cues/`, { method: 'POST', body: data }),
  updateCue: (cueId, data) => request(`/cues/${cueId}/`, { method: 'PATCH', body: data }),
  deleteCue: (cueId) => request(`/cues/${cueId}/`, { method: 'DELETE' }),
  runs: (id) => request(`/productions/${id}/runs/`),
  createRun: (id, data) => request(`/productions/${id}/runs/`, { method: 'POST', body: data }),
  run: (runId) => request(`/runs/${runId}/`),
  // Operator actions return { event, state }.
  go: (runId, cue) => request(`/runs/${runId}/go/`, { method: 'POST', body: cue ? { cue } : {} }),
  back: (runId) => request(`/runs/${runId}/back/`, { method: 'POST' }),
  goto: (runId, cue) => request(`/runs/${runId}/goto/`, { method: 'POST', body: { cue } }),
  reset: (runId) => request(`/runs/${runId}/reset/`, { method: 'POST' }),
  endRun: (runId) => request(`/runs/${runId}/end/`, { method: 'POST' }),
}
