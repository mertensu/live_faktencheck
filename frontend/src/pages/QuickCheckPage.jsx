import { useEffect, useState } from 'react'
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
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [result, setResult] = useState(null)
  const [remaining, setRemaining] = useState(null)
  const [limit, setLimit] = useState(null)
  const [history, setHistory] = useState([])
  const [selectedClaim, setSelectedClaim] = useState(null)

  const loadHistory = async () => setHistory(await fetchQuickCheckHistory())

  useEffect(() => { if (getAccessCode()) loadHistory() }, [])

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

        <form onSubmit={handleSubmit} className="new-session-form">
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

          <div className="form-field">
            <label htmlFor="qc-claim">Behauptung *</label>
            <textarea
              id="qc-claim"
              value={claim}
              onChange={e => setClaim(e.target.value)}
              required
              rows={4}
              maxLength={1000}
              placeholder="z.B. Die Inflation lag 2024 bei 2 Prozent."
            />
          </div>

          {error && <p className="form-error">{error}</p>}

          <div className="form-actions">
            <button type="submit" className="action-button primary" disabled={submitting}>
              {submitting ? 'Prüfe …' : 'Behauptung prüfen'}
            </button>
          </div>
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
