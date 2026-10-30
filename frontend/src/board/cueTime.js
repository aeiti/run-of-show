// Cue timing, shown the way Eos shows it. The API sends seconds as strings
// ("3.9", "60") or null.

/** How long BACK takes to settle on the previous cue. */
export const BACK_FADE = 1

const seconds = (value) => (value == null || value === '' ? null : Number(value))

/** 3.9 -> "3.9", 60 -> "1:00", 90.5 -> "1:30.5", null -> "". */
export function formatSeconds(value) {
  const s = seconds(value)
  if (s == null) return ''
  if (s < 60) return String(s)
  const m = Math.floor(s / 60)
  const [whole, frac] = String(Math.round((s - m * 60) * 100) / 100).split('.')
  return `${m}:${whole.padStart(2, '0')}${frac ? `.${frac}` : ''}`
}

/** "5", or "5/3" when the down time differs; "" for a cue with no time of its own (a part cue). */
export function formatTime(cue) {
  const up = seconds(cue.time)
  const down = seconds(cue.down_time)
  if (up == null) return ''
  return down != null && down !== up ? `${formatSeconds(up)}/${formatSeconds(down)}` : formatSeconds(up)
}

/** Seconds the cue takes to complete: Eos's total if there is one, otherwise the longer of up and down. */
export function fadeSeconds(cue) {
  const total = seconds(cue.duration)
  if (total != null) return total
  const times = [seconds(cue.time), seconds(cue.down_time)].filter((t) => t != null)
  return times.length ? Math.max(...times) : null
}

/** Eos's total, but only when it says more than the time does (delays, discrete times, parts). */
export function extraTotal(cue) {
  const total = seconds(cue.duration)
  if (total == null) return null
  const times = [seconds(cue.time), seconds(cue.down_time)].filter((t) => t != null)
  return times.length && Math.max(...times) >= total ? null : total
}

/** How long the fade bar runs after an action makes this cue active. */
export const fadeFor = (action, cue) => (action === 'back' ? BACK_FADE : (fadeSeconds(cue) ?? 0))

function parseSeconds(text) {
  const parts = text.split(':')
  if (parts.length > 3 || parts.some((p) => !/^\d+(\.\d+)?$/.test(p))) return null
  const values = parts.map(Number)
  if (values.slice(1).some((v) => v >= 60)) return null
  return String(values.reduce((total, v) => total * 60 + v, 0))
}

/**
 * The Time field in Edit mode: "5", "5/3" (up/down), "1:30", or blank.
 * Returns the API fields, or throws with a message for the operator.
 */
export function parseTimeInput(text) {
  const trimmed = text.trim()
  if (!trimmed) return { time: null, down_time: null }
  const [up, down, extra] = trimmed.split('/').map((s) => s.trim())
  const time = parseSeconds(up)
  const downTime = down === undefined ? null : parseSeconds(down)
  if (extra !== undefined || time == null || (down !== undefined && downTime == null)) {
    throw new Error('Time is seconds or m:ss, with an optional down time: 5, 5/3 or 1:30.')
  }
  return { time, down_time: downTime }
}
