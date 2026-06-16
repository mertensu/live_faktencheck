import { useEffect } from 'react'

function formatLimit(value, unit) {
  if (value == null) return 'unbegrenzt'
  return `max. ${value}${unit ? ` ${unit}` : ''}`
}

export function LimitInfoModal({ info, onClose }) {
  useEffect(() => {
    document.body.style.overflow = 'hidden'
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', handleKey)
    return () => {
      document.body.style.overflow = ''
      window.removeEventListener('keydown', handleKey)
    }
  }, [onClose])

  return (
    <div className="impressum-overlay" onClick={onClose}>
      <div
        className="impressum-modal"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="limit-info-title"
      >
        <button className="impressum-close" onClick={onClose} aria-label="Schließen">×</button>
        <h2 id="limit-info-title">
          Freigeschaltet{info?.name ? ` als ${info.name}` : ''}
        </h2>
        <p>Für deinen Zugang gelten folgende Limits:</p>

        <ul className="limit-info-list">
          <li className="limit-info-item">
            <span className="limit-info-icon" aria-hidden="true">🔎</span>
            <span className="limit-info-label">Behauptungen prüfen</span>
            <span className="limit-info-value">{formatLimit(info?.quick_check_limit)}</span>
          </li>
          <li className="limit-info-item">
            <span className="limit-info-icon" aria-hidden="true">🎙</span>
            <span className="limit-info-label">Live-Audio</span>
            <span className="limit-info-value">{formatLimit(info?.audio_limit_minutes, 'Min')}</span>
          </li>
        </ul>

        <button type="button" className="action-button primary" onClick={onClose}>
          Verstanden
        </button>
      </div>
    </div>
  )
}
