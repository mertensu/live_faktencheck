import { useCallback, useEffect, useRef, useState } from 'react'
import {
  fetchPendingClaims, fetchFactChecks,
  approveClaims, discardClaims, setSessionAutoCheck,
} from '../services/api'
import { SwipeCard } from './SwipeCard'
import { ResultsFeed } from './ResultsFeed'

const POLL_MS = 2000

// Flatten pending blocks (oldest first) into a flat claim queue with stable ids.
const flatten = (blocks) => {
  const out = []
  blocks.forEach((b) =>
    (b.claims || []).forEach((c, i) =>
      out.push({ id: `${b.block_id}-${i}`, name: c.name || '', claim: c.claim || '', timestamp: b.timestamp })
    )
  )
  return out.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
}

export function ReviewView({ sessionId, initialAutoCheck = false, onSelect }) {
  const [auto, setAuto] = useState(initialAutoCheck)
  const [pending, setPending] = useState([])
  const [factChecks, setFactChecks] = useState([])
  const [handledIds, setHandledIds] = useState(() => new Set())
  const [error, setError] = useState(null)
  const handledRef = useRef(handledIds)
  handledRef.current = handledIds

  // Poll pending claims (only meaningful when Auto is off).
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const blocks = await fetchPendingClaims(sessionId)
        if (alive) setPending(flatten(blocks).filter((c) => !handledRef.current.has(c.id)))
      } catch { /* keep last state */ }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [sessionId])

  // Poll fact-check results for the feed.
  useEffect(() => {
    let alive = true
    const tick = async () => {
      try {
        const data = await fetchFactChecks(sessionId)
        if (alive) setFactChecks(data.filter((fc) => fc.status !== 'discarded'))
      } catch { /* keep last state */ }
    }
    tick()
    const t = setInterval(tick, POLL_MS)
    return () => { alive = false; clearInterval(t) }
  }, [sessionId])

  const current = pending[0]

  const advance = useCallback((id) => {
    setHandledIds((prev) => new Set(prev).add(id))
    setPending((prev) => prev.filter((c) => c.id !== id))
  }, [])

  const handleKeep = useCallback(async (edited) => {
    if (!current) return
    try {
      await approveClaims(sessionId, [edited])
      setError(null)
      advance(current.id)
    } catch (e) {
      setError('Konnte nicht senden — bitte erneut versuchen.')
    }
  }, [current, sessionId, advance])

  const handleDiscard = useCallback(async (claim) => {
    if (!current) return
    try {
      await discardClaims(sessionId, [claim])
      setError(null)
      advance(current.id)
    } catch (e) {
      setError('Konnte nicht verwerfen — bitte erneut versuchen.')
    }
  }, [current, sessionId, advance])

  const handleToggleAuto = useCallback(async (e) => {
    const next = e.target.checked
    setAuto(next)
    try {
      await setSessionAutoCheck(sessionId, next)
    } catch {
      setAuto(!next)  // revert on failure
      setError('Auto-Prüfung konnte nicht umgeschaltet werden.')
    }
  }, [sessionId])

  return (
    <div className="review-view">
      <div className="review-controls">
        <label className="auto-toggle">
          <input type="checkbox" checked={auto} onChange={handleToggleAuto} />
          <span>Auto-Prüfung</span>
        </label>
      </div>

      {error && <p className="review-error" role="alert">{error}</p>}

      <div className="review-stage">
        {auto ? (
          <p className="review-auto-status">Automatisch — Handy kann liegen bleiben</p>
        ) : current ? (
          <SwipeCard
            key={current.id}
            claim={current}
            remaining={pending.length}
            onKeep={handleKeep}
            onDiscard={handleDiscard}
          />
        ) : (
          <p className="review-waiting">Warte auf Aussagen…</p>
        )}
      </div>

      <ResultsFeed factChecks={factChecks} onSelect={onSelect} />
    </div>
  )
}
