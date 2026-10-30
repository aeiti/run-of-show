import { useState } from 'react'
import { api } from '../api'
import ProductionLogo from '../ProductionLogo'

/** Upload, replace or remove the production's logo. Saves straight away, apart from the details form. */
export default function LogoField({ production, onSaved }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function run(fn) {
    setBusy(true)
    setError('')
    try {
      onSaved(await fn())
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  function upload(e) {
    const file = e.target.files[0]
    e.target.value = ''
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    run(() => api.uploadLogo(production.id, form))
  }

  return (
    <div className="span-all logo-field">
      <ProductionLogo production={production} />
      <label>
        Logo (PNG, JPEG, GIF or WebP)
        <input type="file" accept="image/png,image/jpeg,image/gif,image/webp" disabled={busy} onChange={upload} />
      </label>
      {production.logo && (
        <button type="button" className="ghost small" disabled={busy} onClick={() => run(() => api.deleteLogo(production.id))}>
          Remove logo
        </button>
      )}
      {error && <p className="error">{error}</p>}
    </div>
  )
}
