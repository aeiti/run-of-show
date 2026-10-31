import { useEffect, useState } from 'react'
import { api } from '../api'

const LOCAL = ['localhost', '127.0.0.1', '[::1]']
const FIELDS = ['enabled', 'transport', 'port', 'host', 'framing', 'cue_list']

/** "just now", "40s ago", "5 min ago", from an ISO time, kept fresh. */
function useAgo(iso) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    if (!iso) return
    const timer = setInterval(() => setNow(Date.now()), 5000)
    return () => clearInterval(timer)
  }, [iso])
  if (!iso) return null
  const seconds = Math.max(0, Math.round((now - Date.parse(iso)) / 1000))
  if (seconds < 5) return 'just now'
  if (seconds < 60) return `${seconds}s ago`
  return `${Math.round(seconds / 60)} min ago`
}

const LABELS = {
  starting: 'Starting…',
  listening: 'Listening',
  connecting: 'Connecting…',
  connected: 'Connected',
  error: 'Problem',
}

/**
 * The Eos console listener's state, beside "Synced". Editors click it for the
 * settings; when no console is set up, they see a plain "Console" button.
 */
export function ConsoleStatus({ info, canEdit, onOpen }) {
  const status = info?.status
  const ago = useAgo(status?.heard)
  if (!status || (status.state === 'off' && !canEdit)) return null
  if (status.state === 'off') {
    return (
      <button className="ghost small console-button" onClick={onOpen} title="Follow an Eos console's cues">
        Console
      </button>
    )
  }
  const text = status.state === 'error' ? LABELS.error : ago ? `Heard ${ago}` : LABELS[status.state]
  const title = [status.detail, status.problem].filter(Boolean).join('\n')
  const className = `console-status ${status.state}${status.problem ? ' has-problem' : ''}`
  return canEdit ? (
    <button type="button" className={`${className} as-button`} title={title} onClick={onOpen}>
      Console · {text}
    </button>
  ) : (
    <span className={className} role="status" title={title}>
      Console · {text}
    </span>
  )
}

/** Settings for following an Eos console, and what to set on the desk. */
export default function ConsoleDialog({ productionId, info, onSaved, onClose }) {
  const [draft, setDraft] = useState(() => Object.fromEntries(FIELDS.map((f) => [f, info[f]])))
  const [errors, setErrors] = useState({})
  const [saving, setSaving] = useState(false)
  const udp = draft.transport === 'udp'
  const set = (key) => (e) =>
    setDraft({ ...draft, [key]: e.target.type === 'checkbox' ? e.target.checked : e.target.value })

  async function save(e) {
    e.preventDefault()
    setSaving(true)
    setErrors({})
    try {
      onSaved(
        await api.saveConsole(productionId, {
          ...draft,
          port: Number(draft.port),
          cue_list: Number(draft.cue_list),
          host: draft.host.trim(),
        }),
      )
      onClose()
    } catch (err) {
      // Port and address problems go by their fields; anything else below the form.
      const fields = err.data && typeof err.data === 'object' ? err.data : {}
      const byField = (key) => (fields[key] ? [fields[key]].flat().join(' ') : undefined)
      setErrors({ host: byField('host'), port: byField('port'), detail: fields.host || fields.port ? '' : err.message })
    } finally {
      setSaving(false)
    }
  }

  const here = window.location.hostname
  const status = info.status

  return (
    <div className="dialog-backdrop" role="presentation" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <section className="dialog console-dialog panel" role="dialog" aria-modal="true" aria-labelledby="console-title">
        <div className="row-between">
          <h2 id="console-title">Eos console</h2>
          <button className="ghost small" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <p className="muted small-print">
          Each cue the console fires is recorded on the open run, as a GO, or a GOTO when the console goes back. The
          app only listens; it never sends anything to the console.
        </p>
        {status.state !== 'off' && (
          <p className={`console-now ${status.state}`}>
            {status.detail}
            {status.problem && <span className="console-problem">{status.problem}</span>}
          </p>
        )}

        <form onSubmit={save}>
          <label className="check">
            <input type="checkbox" checked={draft.enabled} onChange={set('enabled')} />
            Follow this console
          </label>
          <div className="field-grid">
            <label>
              Connection
              <select value={draft.transport} onChange={set('transport')}>
                <option value="udp">UDP</option>
                <option value="tcp">TCP</option>
              </select>
            </label>
            {!udp && (
              <label>
                Console IP address
                <input value={draft.host} onChange={set('host')} placeholder="10.101.100.101" required />
                {errors.host && <span className="error">{errors.host}</span>}
              </label>
            )}
            <label>
              Port
              <input type="number" min={1} max={65535} value={draft.port} onChange={set('port')} required />
              {errors.port && <span className="error">{errors.port}</span>}
            </label>
            {!udp && (
              <label>
                OSC TCP mode
                <select value={draft.framing} onChange={set('framing')}>
                  <option value="1.0">OSC 1.0 (the console&apos;s default)</option>
                  <option value="1.1">OSC 1.1 (SLIP)</option>
                </select>
              </label>
            )}
            <label>
              Cue list
              <input type="number" min={1} value={draft.cue_list} onChange={set('cue_list')} required />
            </label>
          </div>

          <div className="console-help small-print">
            <b>On the console</b>, in Setup &gt; System &gt; Show Control &gt; OSC:
            {udp ? (
              <>
                {' '}
                turn on OSC TX, set OSC TX IP Address to this server&apos;s address
                {LOCAL.includes(here) ? '' : ` (${here})`} and OSC TX Port to {draft.port || '…'}. In the ECU, enable
                UDP Strings &amp; OSC for that network interface.
                {LOCAL.includes(here) && (
                  <span className="muted">
                    {' '}
                    This board is open on localhost, so use this computer&apos;s network address.
                  </span>
                )}
              </>
            ) : (
              <> turn on OSC RX and OSC TX, and set the OSC TCP mode to match. The app connects and only reads.</>
            )}{' '}
            Leave OSC Cue Send String empty.
          </div>

          {errors.detail && <p className="error">{errors.detail}</p>}
          <div className="row">
            <button type="submit" disabled={saving}>
              Save
            </button>
            <button type="button" className="ghost" onClick={onClose}>
              Cancel
            </button>
          </div>
        </form>
      </section>
    </div>
  )
}
