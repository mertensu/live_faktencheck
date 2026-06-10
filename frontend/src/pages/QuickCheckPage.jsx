import { useEffect, useRef, useState } from 'react'
import { ClaimCard } from '../components/ClaimCard'
import { ClaimDetailOverlay } from '../components/ClaimDetailOverlay'
import {
  submitQuickCheck,
  fetchQuickCheckHistory,
  getAccessCode,
  setAccessCode,
} from '../services/api'

export function QuickCheckPage() {
  const [claim, setClaim] = useState('')
  const [accessCode, setAccessCodeInput] = useState(getAccessCode())
  // Only ask for a code when none is stored yet (deep-link fallback); the
  // homepage unlock normally provides it. Re-shown if the stored code fails.
  const [needsCode, setNeedsCode] = useState(!getAccessCode())
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [remaining, setRemaining] = useState(null)
  const [limit, setLimit] = useState(null)
  const [history, setHistory] = useState([])
  const [selectedClaim, setSelectedClaim] = useState(null)

  const claimRef = useRef(null)

  const loadHistory = async () => setHistory(await fetchQuickCheckHistory())

  useEffect(() => { if (getAccessCode()) loadHistory() }, [])

  // Auto-grow the prompt box with its content (capped), and reset on clear.
  useEffect(() => {
    const el = claimRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [claim])

  // Enter submits; Shift+Enter inserts a newline.
  const handleKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (!submitting && claim.trim()) e.currentTarget.form?.requestSubmit()
    }
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    setResult(null)
    setSubmitting(true)
    setAccessCode(accessCode.trim())
    try {
      const data = await submitQuickCheck(claim.trim())
      setResult(data.fact_check)
      setLimit(data.limit)
      setRemaining(data.remaining)
      setClaim('')
      await loadHistory()
    } catch (err) {
      const msg = err.message || 'Unbekannter Fehler'
      setError(msg)
      if (/401|403|Zugangscode/i.test(msg)) {
        setAccessCode('')
        setAccessCodeInput('')
        setNeedsCode(true)
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Einzelne Behauptung prüfen</h1>
        <p>Füge ein Zitat oder eine Aussage ein und erhalte einen Faktencheck.</p>

        <form onSubmit={handleSubmit} className="quick-check-form">
          {needsCode && (
            <div className="form-field">
              <label htmlFor="qc-code">Zugangscode *</label>
              <input
                id="qc-code"
                type="password"
                value={accessCode}
                onChange={e => setAccessCodeInput(e.target.value)}
                required
                autoComplete="off"
                placeholder="Dein persönlicher Zugangscode"
              />
            </div>
          )}

          <div className="claim-box">
            <svg className="claim-box-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
              <circle cx="11" cy="11" r="7" />
              <path d="m21 21-4.3-4.3" />
            </svg>
            <textarea
              ref={claimRef}
              id="qc-claim"
              className="claim-box-input"
              value={claim}
              onChange={e => setClaim(e.target.value)}
              onKeyDown={handleKeyDown}
              required
              rows={1}
              maxLength={1000}
              placeholder="Behauptung eingeben – z.B. Die Inflation lag 2024 bei 2 Prozent."
            />
            <button
              type="submit"
              className="claim-box-send"
              disabled={submitting || !claim.trim()}
              aria-label="Behauptung prüfen"
            >
              {submitting ? (
                <span className="claim-box-spinner" aria-hidden="true" />
              ) : (
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M12 19V5M5 12l7-7 7 7" />
                </svg>
              )}
            </button>
          </div>

          {error && <p className="form-error">{error}</p>}
        </form>

        {limit !== null && remaining !== null && (
          <p className="quota-note">Noch {remaining} von {limit} Prüfungen übrig.</p>
        )}

        {result && (
          <div className="quick-check-result">
            <h2>Ergebnis</h2>
            <ClaimCard claim={result} onSelect={setSelectedClaim} />
          </div>
        )}

        {history.length > 0 && (
          <div className="quick-check-history">
            <h2>Frühere Prüfungen</h2>
            {history.map(fc => (
              <ClaimCard key={fc.id} claim={fc} onSelect={setSelectedClaim} />
            ))}
          </div>
        )}

        {selectedClaim && (
          <ClaimDetailOverlay
            claim={selectedClaim}
            onClose={() => setSelectedClaim(null)}
          />
        )}
      </div>
    </div>
  )
}
