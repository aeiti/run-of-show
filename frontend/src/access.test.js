import { describe, expect, it } from 'vitest'
import { can, MEMBER_ROLES, ROLES } from './access'

describe('can', () => {
  it('gives each role only its own jobs', () => {
    const jobs = (role) => ['view', 'operate', 'edit', 'share', 'delete'].filter((c) => can(role, c))
    expect(jobs('owner')).toEqual(['view', 'operate', 'edit', 'share', 'delete'])
    expect(jobs('stage_manager')).toEqual(['view', 'operate', 'edit', 'share'])
    expect(jobs('operator')).toEqual(['view', 'operate'])
    expect(jobs('viewer')).toEqual(['view'])
  })

  it('refuses an unknown or missing role', () => {
    expect(can(undefined, 'view')).toBe(false)
    expect(can('admin', 'operate')).toBe(false)
  })

  it('has a label for every role, and never offers owner to a member', () => {
    expect(Object.keys(ROLES)).toEqual(['owner', ...MEMBER_ROLES])
  })
})
