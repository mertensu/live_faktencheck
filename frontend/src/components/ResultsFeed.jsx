import { ClaimCard } from './ClaimCard'

// Vertical feed of fact-check result cards, newest first. Reuses ClaimCard,
// which already renders processing spinners and error states.
export function ResultsFeed({ factChecks, onSelect }) {
  if (!factChecks || factChecks.length === 0) {
    return <p className="results-empty">Noch keine Ergebnisse</p>
  }
  const ordered = [...factChecks].sort(
    (a, b) => new Date(b.timestamp || 0) - new Date(a.timestamp || 0)
  )
  return (
    <div className="results-feed">
      {ordered.map((fc) => (
        <div key={fc.id} className="results-feed-item">
          {fc.sprecher && (
            <div className="results-feed-speaker">{fc.sprecher}</div>
          )}
          <ClaimCard claim={fc} onSelect={onSelect} />
        </div>
      ))}
    </div>
  )
}
