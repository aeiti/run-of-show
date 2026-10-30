import { describe, expect, it } from 'vitest'
import { currentScript, formatSize, groupFiles } from './files'

const file = (id, kind, name, version, uploaded_at) => ({ id, kind, name, version, uploaded_at })

const files = [
  file(1, 'other', 'Rigging.pdf', 1, '2026-03-01T10:00:00Z'),
  file(2, 'showfile', 'show.esf', 1, '2026-03-01T10:00:00Z'),
  file(3, 'script', 'Act 2.pdf', 1, '2026-03-02T10:00:00Z'),
  file(4, 'showfile', 'show.esf', 2, '2026-03-03T10:00:00Z'),
  file(5, 'script', 'Act 1.pdf', 1, '2026-03-01T10:00:00Z'),
  file(6, 'script', 'Act 1.pdf', 2, '2026-03-01T12:00:00Z'),
]

describe('groupFiles', () => {
  it('groups versions by kind and name, scripts first, then by name', () => {
    expect(groupFiles(files).map((g) => [g.kind, g.name, g.versions.map((v) => v.version)])).toEqual([
      ['script', 'Act 1.pdf', [2, 1]],
      ['script', 'Act 2.pdf', [1]],
      ['showfile', 'show.esf', [2, 1]],
      ['other', 'Rigging.pdf', [1]],
    ])
  })

  it('keeps the same name under different kinds apart', () => {
    const groups = groupFiles([file(1, 'other', 'a.pdf', 1, 'x'), file(2, 'script', 'a.pdf', 1, 'x')])
    expect(groups.map((g) => g.kind)).toEqual(['script', 'other'])
  })
})

describe('currentScript', () => {
  it('is the script uploaded last, not the highest version', () => {
    expect(currentScript(files).id).toBe(3)
  })

  it('is null without a script', () => {
    expect(currentScript(files.filter((f) => f.kind !== 'script'))).toBeNull()
  })
})

describe('formatSize', () => {
  it('uses bytes, KB and MB', () => {
    expect([formatSize(900), formatSize(2048), formatSize(5.25 * 1024 * 1024)]).toEqual(['900 B', '2 KB', '5.3 MB'])
  })
})
