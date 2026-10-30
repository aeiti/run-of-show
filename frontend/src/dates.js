// Pure helpers for production dates and run times. `locale` is only passed by tests.

/** "2026-11-14" as a local date: new Date("2026-11-14") would be UTC midnight, the day before in the Americas. */
function localDate(value) {
  const [y, m, d] = value.split('-').map(Number)
  return new Date(y, m - 1, d)
}

const DAY = { day: 'numeric', month: 'short', year: 'numeric' }

/** Opening and closing dates as one phrase: "14–29 Nov 2026", "Opens 14 Nov 2026", or "". */
export function formatDateRange(opening, closing, locale) {
  const format = new Intl.DateTimeFormat(locale, DAY)
  if (opening && closing) return format.formatRange(localDate(opening), localDate(closing))
  if (opening) return `Opens ${format.format(localDate(opening))}`
  if (closing) return `Closes ${format.format(localDate(closing))}`
  return ''
}

/** An ISO time as a datetime-local input's value ("2026-03-14T19:30"), in local time. */
export function toLocalInput(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  const pad = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

/** A datetime-local input's value as an ISO time, or null when it's empty. */
export function fromLocalInput(value) {
  return value ? new Date(value).toISOString() : null
}

/**
 * When a time typed into the form is the same minute as the saved one, keep
 * the saved one: the input only shows minutes, and saving it would drop the seconds.
 */
export function keepSeconds(saved, typed) {
  if (!saved || !typed) return typed
  return toLocalInput(saved) === toLocalInput(typed) ? saved : typed
}

/** Seconds between two ISO times (or `now`, in ms, for an open end); null if there's no start. */
export function secondsBetween(start, end, now = Date.now()) {
  if (!start) return null
  return Math.max(0, ((end ? Date.parse(end) : now) - Date.parse(start)) / 1000)
}

/** How late (positive) or early (negative) a run went up, in whole minutes; null without both times. */
export function minutesLate(scheduled, started) {
  if (!scheduled || !started) return null
  return Math.round((Date.parse(started) - Date.parse(scheduled)) / 60000)
}

/** "+4 min", "−2 min", "on time". */
export function formatLateness(minutes) {
  if (minutes === null) return ''
  if (minutes === 0) return 'on time'
  return `${minutes > 0 ? '+' : '−'}${Math.abs(minutes)} min`
}
