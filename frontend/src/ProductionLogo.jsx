import { api } from './api'
import { useBlobUrl } from './useBlobUrl'

/** The production's logo, if it has one. ``production.logo`` changes whenever the image does. */
export default function ProductionLogo({ production, className = 'production-logo' }) {
  const key = production.logo ? `${production.id}/${production.logo}` : null
  const { url } = useBlobUrl(() => api.logoBlob(production.id), key)
  return url ? <img className={className} src={url} alt="" /> : null
}
