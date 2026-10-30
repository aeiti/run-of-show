import { useState } from 'react'

/**
 * GO / BACK / GOTO / RESET. The board owns the run and the loaded cue; this
 * only renders the buttons and reports which action was asked for.
 */
export default function Transport({
  disabled,
  goLabel,
  canGo,
  canBack,
  nextText,
  gotoText,
  onGotoText,
  gotoTarget,
  gotoRef,
  onAction,
}) {
  const [confirmReset, setConfirmReset] = useState(false)

  function reset() {
    if (!confirmReset) {
      setConfirmReset(true)
      setTimeout(() => setConfirmReset(false), 3000)
      return
    }
    setConfirmReset(false)
    onAction('reset')
  }

  return (
    <div className="transport">
      <button className="go" onClick={() => onAction('go')} disabled={disabled || !canGo}>
        {goLabel}
      </button>
      <p className="muted next">{nextText}</p>

      <div className="transport-row">
        <button className="ghost" onClick={() => onAction('back')} disabled={disabled || !canBack} title="B or ←">
          BACK
        </button>
        <form
          className="goto"
          onSubmit={(e) => {
            e.preventDefault()
            if (!gotoTarget) return
            onAction('goto', gotoTarget.id)
            // Hand the keyboard back to the board so the next Space is GO, not a typed space.
            gotoRef.current?.blur()
          }}
        >
          <input
            ref={gotoRef}
            aria-label="Cue number to go to"
            placeholder="Q#"
            inputMode="decimal"
            value={gotoText}
            onChange={(e) => onGotoText(e.target.value)}
          />
          <button className="ghost" type="submit" disabled={disabled || !gotoTarget} title="G to type a cue number">
            GOTO
          </button>
        </form>
        <button className={`ghost ${confirmReset ? 'danger' : ''}`} onClick={reset} disabled={disabled}>
          {confirmReset ? 'Confirm' : 'RESET'}
        </button>
      </div>
      <p className="muted keys">Space GO · B BACK · G GOTO · ↑↓ load · Esc unload</p>
    </div>
  )
}
