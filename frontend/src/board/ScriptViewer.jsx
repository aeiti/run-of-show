import { api } from '../api'
import { useBlobUrl } from '../useBlobUrl'

/**
 * The production's script beside the cue list, in the browser's own PDF
 * viewer. ``page`` is the active cue's script page, passed as the URL's
 * #page= fragment. Chrome's viewer only reads the fragment when it loads, so
 * the frame is remounted (keyed by page) when the page changes; the blob is
 * already in memory, so nothing is fetched again.
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
        <iframe key={page ?? 0} title={`Script: ${file.name}`} src={page ? `${url}#page=${page}` : url} />
      ) : (
        <p className="muted">Loading the script…</p>
      )}
    </section>
  )
}
