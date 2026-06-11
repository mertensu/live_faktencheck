import { useRef, useState } from 'react'

const SWIPE_THRESHOLD = 90  // px of horizontal drag to commit

export function SwipeCard({ claim, remaining, onKeep, onDiscard }) {
  const [editing, setEditing] = useState(false)
  const [name, setName] = useState(claim.name || '')
  const [text, setText] = useState(claim.claim || '')
  const [dx, setDx] = useState(0)
  const startX = useRef(null)

  const keep = () => onKeep({ name, claim: text })
  const discard = () => onDiscard({ name: claim.name || '', claim: claim.claim || '' })

  const onPointerDown = (e) => {
    startX.current = e.clientX
    setDx(0)
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }
  const onPointerMove = (e) => { if (startX.current !== null) setDx(e.clientX - startX.current) }
  const onPointerUp = () => {
    if (startX.current === null) return
    const delta = dx
    startX.current = null
    setDx(0)
    if (delta > SWIPE_THRESHOLD) keep()
    else if (delta < -SWIPE_THRESHOLD) discard()
  }

  return (
    <div className="swipe-card-wrap">
      <p className="swipe-remaining">noch {remaining}</p>
      <div
        className="swipe-card"
        style={{ transform: `translateX(${dx}px)`, touchAction: 'pan-y' }}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerCancel={onPointerUp}
      >
        {editing ? (
          <div className="swipe-edit">
            <label>
              <span>Sprecher</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <label>
              <span>Aussage</span>
              <textarea value={text} onChange={(e) => setText(e.target.value)} />
            </label>
            <button type="button" onClick={keep}>Prüfen</button>
          </div>
        ) : (
          <>
            <p className="swipe-speaker">{claim.name}</p>
            <p className="swipe-claim">{claim.claim}</p>
            <button type="button" className="swipe-edit-toggle" onClick={() => setEditing(true)}>
              Bearbeiten
            </button>
          </>
        )}
      </div>
      <div className="swipe-actions">
        <button type="button" className="swipe-discard" onClick={discard}>Verwerfen</button>
        <button type="button" className="swipe-keep" onClick={keep}>Behalten</button>
      </div>
    </div>
  )
}
