import { useEffect } from 'react'
import { getConsistencyColor, getConsistencyClass, formatBegruendung } from './ClaimCard'

export function ClaimDetailOverlay({ claim, onClose }) {
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  const consistencyClass = getConsistencyClass(claim.consistency)

  return (
    <div className="claim-detail-backdrop" onClick={onClose}>
      <div className="claim-detail-panel" onClick={(e) => e.stopPropagation()}>
        <button className="claim-detail-close" onClick={onClose} aria-label="Schließen">
          ← Zurück
        </button>

        <div className="claim-detail-body">
          {claim.sprecher && (
            <div className="claim-detail-speaker">{claim.sprecher}</div>
          )}

          <h2 className="claim-detail-heading">{claim.behauptung}</h2>

          {claim.consistency && (
            <div className="claim-detail-verdict-row">
              <div
                className="verdict-badge"
                style={{ backgroundColor: getConsistencyColor(claim.consistency) }}
              >
                {claim.consistency}
              </div>
              <span className="claim-detail-verdict-label">Datenbasierte Fundierung</span>
            </div>
          )}

          <div className={`claim-detail-card ${consistencyClass}`}>
            <h3 className="claim-detail-section-title">Begründung</h3>
            {claim.begruendung ? (
              <div className="begruendung-container">
                {formatBegruendung(claim.begruendung)}
              </div>
            ) : (
              <p className="begruendung-text no-begruendung">Keine Begründung verfügbar</p>
            )}

            {claim.quellen && claim.quellen.length > 0 && (
              <>
                <h3 className="claim-detail-section-title">Quellen</h3>
                <ul className="sources-list">
                  {claim.quellen.map((quelle, idx) => {
                    const url = typeof quelle === 'object' ? quelle.url : quelle
                    const title = typeof quelle === 'object' && quelle.title ? quelle.title : url
                    return (
                      <li key={idx}>
                        <a
                          href={url}
                          target="_blank"
                          rel="noopener noreferrer"
                          className="source-link"
                        >
                          {title}
                        </a>
                      </li>
                    )
                  })}
                </ul>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
