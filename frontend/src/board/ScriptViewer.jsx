import { api } from '../api'
import { useBlobUrl } from '../useBlobUrl'

/**
 * The production's script beside the cue list, in the browser's own PDF
 * viewer. ``page`` is the active cue's script page; on each GO the viewer is
 * sent there with the URL's #page= fragment, which the built-in viewers in
 * Chrome, Firefox and Safari understand. Only the fragment changes, so the
 * file isn't fetched again.
 */
export default function ScriptViewer({ file, page }) {
  const { url, error } = useBlobUrl(() => api.fileBlob(file.id), file.id)

  return (
    <section className="script-viewer" aria-label="Script">
      <p className="muted script-title">
        {file.name} · v{file.version}
        {page ? ` · p.${page}` : ''}
      </p>
      {error ? (
        <p className="error">{error}</p>
      ) : url ? (
        <iframe title={`Script: ${file.name}`} src={page ? `${url}#page=${page}` : url} />
      ) : (
        <p className="muted">Loading the script…</p>
      )}
    </section>
  )
}
