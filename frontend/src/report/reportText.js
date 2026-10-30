// Pure helpers for the show report page. The numbers come from the server (shows/report.py).

import { formatClock } from '../board/playbackSteps'

/** A length in seconds as "1:02:03", or "–" when there isn't one. */
export function length(seconds) {
  return seconds === null || seconds === undefined ? '–' : formatClock(seconds)
}

/** "4:00 late", "2:00 early", "on time" (within a minute), or "" without both times. */
export function lateness(seconds) {
  if (seconds === null || seconds === undefined) return ''
  if (Math.abs(seconds) < 60) return 'on time'
  return `${formatClock(Math.abs(seconds))} ${seconds > 0 ? 'late' : 'early'}`
}

/** A scene's name; the cues before the first scene have none. */
export const sceneName = (scene) => scene.name || 'Before the first scene'

/** "Q12 Lightning", "Q12", or "" for no cue. */
export const cueText = (number, label = '') => [number && `Q${number}`, label].filter(Boolean).join(' ')

/**
 * Addresses typed into one box, split on commas, semicolons, spaces or new
 * lines, without repeats (ignoring case). The server checks each one.
 */
export function parseAddresses(text) {
  const seen = new Set()
  return text
    .split(/[\s,;]+/)
    .map((a) => a.trim())
    .filter((a) => {
      const key = a.toLowerCase()
      if (!a || seen.has(key)) return false
      seen.add(key)
      return true
    })
}
