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
  events: (id, run) => request(`/productions/${id}/events/?run=${encodeURIComponent(run)}`),
  fire: (cueId, runLabel) =>
    request(`/cues/${cueId}/fire/`, { method: 'POST', body: { run_label: runLabel } }),
}
