// What each role on a production may do. Mirrors CAN in backend/shows/access.py;
// the server enforces it, and the board uses it to show only what will work.
export const ROLES = {
  owner: 'Owner',
  stage_manager: 'Stage manager',
  operator: 'Operator',
  viewer: 'Viewer',
}

// Roles a member can be given; there is only one owner.
export const MEMBER_ROLES = ['stage_manager', 'operator', 'viewer']

const CAN = {
  view: ['owner', 'stage_manager', 'operator', 'viewer'],
  operate: ['owner', 'stage_manager', 'operator'],
  edit: ['owner', 'stage_manager'],
  share: ['owner', 'stage_manager'],
  delete: ['owner'],
}

export const can = (role, capability) => CAN[capability].includes(role)
