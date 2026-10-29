// Card looks shared by the live board and playback. GSAP tweens these onto
// each card's .cue-inner; React never sets these properties itself.
// Frozen because GSAP writes into any vars object it is handed: pass a copy
// ({ ...LOOK.active }), and a call that forgets will throw instead of
// quietly corrupting every later tween.
const STANDBY = Object.freeze({ backgroundColor: '#22262d', borderColor: '#8a929e', opacity: 1, scale: 1 })

export const LOOK = Object.freeze({
  pending: Object.freeze({ backgroundColor: '#14171c', borderColor: '#262b33', opacity: 0.7, scale: 1 }),
  standby: STANDBY,
  loaded: STANDBY,
  active: Object.freeze({ backgroundColor: '#3a2d0a', borderColor: '#e8b730', opacity: 1, scale: 1.02 }),
  complete: Object.freeze({ backgroundColor: '#101216', borderColor: '#1d2026', opacity: 0.4, scale: 1 }),
})

export const FLASH = Object.freeze({
  from: Object.freeze({ boxShadow: '0 0 0 8px rgba(232, 183, 48, 0.55)' }),
  to: Object.freeze({ boxShadow: '0 0 0 0px rgba(232, 183, 48, 0)', duration: 0.6, ease: 'power2.out' }),
})

export const STATUS = { complete: 'DONE', active: 'GO', loaded: 'LOAD', standby: 'STBY', pending: '' }

// Playhead sits over the centre of cue i on the track; -1 is "before the top of show".
export const playheadPos = (i, n) => (i < 0 || n === 0 ? '0%' : `${((i + 0.5) / n) * 100}%`)
