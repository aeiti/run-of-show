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

/** Where the show was for a note: "Q12 Lightning · 1.2 Wreck", or just the scene. */
export const noteWhere = (note) => [cueText(note.cue_number, note.cue_label), note.scene].filter(Boolean).join(' · ')

/**
 * The moment for a note added later, from a time of day ("21:05") typed for
 * the run that started (or was due to start) at ``baseIso``. A time more than
 * 12 hours before the start is taken to be after midnight. Returns an ISO
 * string, or null for no time.
 */
export function noteMoment(time, baseIso) {
  const match = /^(\d{1,2}):(\d{2})$/.exec(time.trim())
  if (!match) return null
  const base = new Date(baseIso)
  const moment = new Date(base)
  moment.setHours(Number(match[1]), Number(match[2]), 0, 0)
  if (base - moment > 12 * 3600 * 1000) moment.setDate(moment.getDate() + 1)
  return moment.toISOString()
}

/** Where unsorted notes go in the distributed report. */
export const OTHER_NOTES = 'Other notes'

/**
 * [section, notes] pairs, as the server groups them for email: every one of
 * the production's sections in order, even with no notes; then sections no
 * longer in its list that notes still name; then unsorted notes, if any.
 */
export function bySection(sections, notes) {
  const groups = new Map(sections.map((name) => [name, []]))
  const unsorted = []
  for (const note of notes) {
    if (!note.section) unsorted.push(note)
    else if (groups.has(note.section)) groups.get(note.section).push(note)
    else groups.set(note.section, [note])
  }
  const pairs = [...groups]
  return unsorted.length ? [...pairs, [OTHER_NOTES, unsorted]] : pairs
}

/**
 * The SM's working view: scene changes, holds and notes in the order they
 * happened. Notes with no time come last, in the server's order.
 */
export function timeline(scenes, holds, notes) {
  const timed = [
    ...scenes.map((scene, i) => ({ kind: 'scene', key: `s${i}`, at: scene.started_at, scene })),
    ...holds.map((hold, i) => ({ kind: 'hold', key: `h${i}`, at: hold.started_at, hold })),
    ...notes.filter((n) => n.at).map((note) => ({ kind: 'note', key: `n${note.id}`, at: note.at, note })),
  ]
  // Stable, so a scene or hold comes before a note written at the same moment.
  timed.sort((a, b) => Date.parse(a.at) - Date.parse(b.at))
  const untimed = notes.filter((n) => !n.at).map((note) => ({ kind: 'note', key: `n${note.id}`, at: null, note }))
  return [...timed, ...untimed]
}
