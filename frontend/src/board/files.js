// Production files arrive as one row per version. These group them for the
// files dialog and pick the script the board shows.

export const KINDS = { script: 'Script', showfile: 'Showfile', other: 'Other' }

/** One entry per kind and name, scripts first, each with its versions newest first. */
export function groupFiles(files) {
  const groups = new Map()
  for (const f of files) {
    const key = `${f.kind}\u0000${f.name}`
    if (!groups.has(key)) groups.set(key, { kind: f.kind, name: f.name, versions: [] })
    groups.get(key).versions.push(f)
  }
  const order = Object.keys(KINDS)
  return [...groups.values()]
    .map((g) => ({ ...g, versions: g.versions.toSorted((a, b) => b.version - a.version) }))
    .toSorted((a, b) => order.indexOf(a.kind) - order.indexOf(b.kind) || a.name.localeCompare(b.name))
}

/** The script uploaded most recently (a new version counts), or null. */
export function currentScript(files) {
  return (
    files
      .filter((f) => f.kind === 'script')
      .toSorted((a, b) => b.uploaded_at.localeCompare(a.uploaded_at) || b.id - a.id)[0] ?? null
  )
}

export function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
