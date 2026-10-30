// Layout for the playhead track. Every cue owns an equal slice of the track,
// and the playhead sits over the middle of its slice (see playheadPos).

// The track's cue numbers are 0.65rem JetBrains Mono: about 6.3px a character.
const CHAR_PX = 6.5
const LABEL_GAP = 10

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), hi)

// Scenes as runs of cues: a cue with a scene starts one, which lasts until the
// next cue that has a scene. Cues before the first scene belong to none.
export function sceneSpans(cues) {
  const spans = []
  cues.forEach((c, i) => {
    if (!c.scene) return
    if (spans.length) spans[spans.length - 1].end = i
    spans.push({ name: c.scene, start: i, end: cues.length })
  })
  return spans
}

// Which cues get their number on a track `width` px wide, and where. A long
// show has room for a fraction of them, so they are taken in priority order
// (first and last, then the first cue of each scene, then whole numbers, then
// the rest) and any label that would overlap one already placed is skipped.
// Labels are clamped inside the track; `x` is where the cue's tick goes.
export function trackLabels(cues, width) {
  const n = cues.length
  if (!n || width <= 0) return []

  const box = (i) => {
    const x = ((i + 0.5) / n) * width
    const w = String(cues[i].number).length * CHAR_PX
    const left = clamp(x - w / 2, 0, Math.max(0, width - w))
    return { index: i, x, left, right: left + w }
  }
  const rank = (i) => {
    if (i === 0 || i === n - 1) return 0
    if (cues[i].scene) return 1
    if (Number.isInteger(Number(cues[i].number))) return 2
    return 3
  }

  const order = cues.map((_, i) => i).sort((a, b) => rank(a) - rank(b) || a - b)
  const placed = []
  for (const i of order) {
    const b = box(i)
    if (placed.every((p) => b.right + LABEL_GAP <= p.left || b.left >= p.right + LABEL_GAP)) placed.push(b)
  }
  return placed.sort((a, b) => a.index - b.index)
}
