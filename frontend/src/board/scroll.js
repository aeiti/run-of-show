/**
 * Where to scroll a list so ``card`` is in view, and ``after`` (the standby cue)
 * below it if there's room, moving the list as little as possible: the list's
 * scrollTop for that, or null if they're already in view. ``scrollIntoView``
 * would scroll every scrolling ancestor, the page included, and take the GO
 * button and the note box off screen with it.
 */
export function nearestScrollTop(list, card, after = card) {
  const listTop = list.getBoundingClientRect().top
  const top = card.getBoundingClientRect().top - listTop
  const bottom = after.getBoundingClientRect().bottom - listTop
  if (top < 0) return list.scrollTop + top
  // The card's own top wins over room for the one after it.
  if (bottom > list.clientHeight) return list.scrollTop + Math.min(top, bottom - list.clientHeight)
  return null
}

/** Scroll the cue list holding ``card`` so it, and ``after`` if given, are in view. Only the list moves. */
export function scrollCardIntoList(card, after) {
  const list = card.closest('.cue-list')
  if (!list) return
  const top = nearestScrollTop(list, card, after ?? card)
  if (top != null) list.scrollTo({ top, behavior: 'smooth' })
}
