import { useCallback, useEffect, useRef, useState } from 'react'
import { setFactCheckDiscarded } from '../services/api'

const UNDO_MS = 6000

// "Verwerfen" for the session owner: a check disappears at once (no confirm dialog — too
// slow on air) and a short "Rückgängig" notice brings it back. `hidden` holds the ids
// to leave out until the next poll no longer returns them. Requests run one after the
// other, so a quick undo can't overtake its discard.
export function useDiscard() {
  const [hidden, setHidden] = useState(() => new Set())
  const [notice, setNotice] = useState(null) // { id } or { error }
  const timer = useRef(null)
  const queue = useRef(Promise.resolve())

  const show = useCallback((n) => {
    clearTimeout(timer.current)
    setNotice(n)
    timer.current = setTimeout(() => setNotice(null), UNDO_MS)
  }, [])
  useEffect(() => () => clearTimeout(timer.current), [])

  const mark = useCallback((id, on) => setHidden((prev) => {
    const next = new Set(prev)
    if (on) next.add(id)
    else next.delete(id)
    return next
  }), [])

  const send = useCallback((id, on) => {
    queue.current = queue.current.then(() => setFactCheckDiscarded(id, on)).catch(() => {
      mark(id, !on)
      show({ error: on ? 'Verwerfen fehlgeschlagen.' : 'Wiederherstellen fehlgeschlagen.' })
    })
  }, [mark, show])

  const discard = useCallback((id) => { mark(id, true); show({ id }); send(id, true) }, [mark, show, send])
  const undo = (id) => { clearTimeout(timer.current); setNotice(null); mark(id, false); send(id, false) }

  const toast = notice && (
    <div className="discard-toast" role="status">
      {notice.error || 'Check verworfen.'}
      {notice.id != null && (
        <button type="button" className="discard-toast-undo" onClick={() => undo(notice.id)}>Rückgängig</button>
      )}
    </div>
  )
  return { hidden, discard, toast }
}
