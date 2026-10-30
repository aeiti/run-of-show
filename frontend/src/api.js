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
    const detail = await res.text()
    throw new Error(`${method} ${path} → ${res.status} ${detail}`)
  }
  return res.status === 204 ? null : res.json()
}

export async function login(username, password) {
  const { token } = await request('/auth/token/', { method: 'POST', body: { username, password } })
  localStorage.setItem(TOKEN_KEY, token)
}

export const api = {
  productions: () => request('/productions/'),
  createProduction: (data) => request('/productions/', { method: 'POST', body: data }),
  production: (id) => request(`/productions/${id}/`),
  cues: (id) => request(`/productions/${id}/cues/`),
  createCue: (id, data) => request(`/productions/${id}/cues/`, { method: 'POST', body: data }),
  runs: (id) => request(`/productions/${id}/runs/`),
  createRun: (id, data) => request(`/productions/${id}/runs/`, { method: 'POST', body: data }),
  run: (runId) => request(`/runs/${runId}/`),
  // Operator actions return { event, state }.
  go: (runId, cue) => request(`/runs/${runId}/go/`, { method: 'POST', body: cue ? { cue } : {} }),
  back: (runId) => request(`/runs/${runId}/back/`, { method: 'POST' }),
  goto: (runId, cue) => request(`/runs/${runId}/goto/`, { method: 'POST', body: { cue } }),
  reset: (runId) => request(`/runs/${runId}/reset/`, { method: 'POST' }),
}
