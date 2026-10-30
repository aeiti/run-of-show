import { useEffect, useState } from 'react'
import { formatClock } from './playbackSteps'

/**
 * GO / BACK / GOTO / RESET, and HOLD / RESUME. The board owns the run and the
 * loaded cue; this only renders the buttons and reports which action was
 * asked for. While the run is held only RESUME is available.
 */
export default function Transport({
  disabled,
  hold,
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
  const cueDisabled = disabled || Boolean(hold)

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
      <button className="go" onClick={() => onAction('go')} disabled={cueDisabled || !canGo}>
        {goLabel}
      </button>
      <p className="muted next">{nextText}</p>

      <div className="transport-row">
        <button className="ghost" onClick={() => onAction('back')} disabled={cueDisabled || !canBack} title="B or ←">
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
          <button className="ghost" type="submit" disabled={cueDisabled || !gotoTarget} title="G to type a cue number">
            GOTO
          </button>
        </form>
        <button className={`ghost ${confirmReset ? 'danger' : ''}`} onClick={reset} disabled={cueDisabled}>
          {confirmReset ? 'Confirm' : 'RESET'}
        </button>
      </div>
      <p className="muted keys">Space GO · B BACK · G GOTO · N note · ↑↓ load · Esc unload</p>
      <HoldControl hold={hold} disabled={disabled} onAction={onAction} />
    </div>
  )
}

/** HOLD asks why before it pauses the run; while held, the reason, a running clock and RESUME. */
function HoldControl({ hold, disabled, onAction }) {
  const [reason, setReason] = useState(null) // null: the form is closed

  if (hold) {
    return (
      <div className="hold-banner" role="status">
        <div className="row-between">
          <strong>
            HOLD <HoldClock since={hold.since} />
          </strong>
          <button className="resume" onClick={() => onAction('resume')} disabled={disabled}>
            RESUME
          </button>
        </div>
        <p className="hold-reason">{hold.reason}</p>
      </div>
    )
  }

  if (reason === null) {
    return (
      <button className="ghost wide" onClick={() => setReason('')} disabled={disabled}>
        HOLD…
      </button>
    )
  }

  return (
    <form
      className="row"
      onSubmit={async (e) => {
        e.preventDefault()
        if (await onAction('hold', reason.trim())) setReason(null)
      }}
    >
      <input
        required
        autoFocus
        maxLength={500}
        aria-label="Reason for the hold"
        placeholder="Why? e.g. audience medical"
        value={reason}
        onChange={(e) => setReason(e.target.value)}
      />
      <button type="submit" disabled={disabled || !reason.trim()}>
        Hold
      </button>
      <button type="button" className="ghost" onClick={() => setReason(null)}>
        Cancel
      </button>
    </form>
  )
}

export function HoldClock({ since }) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return <time dateTime={since}>{formatClock((now - Date.parse(since)) / 1000)}</time>
}
