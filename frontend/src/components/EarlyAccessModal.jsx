import { useEffect } from 'react'
import { AccessUnlock } from './AccessUnlock'

const CONTACT = 'info@live-faktencheck.de'
const MAILTO = `mailto:${CONTACT}?subject=${encodeURIComponent('Early Access Live-Faktencheck')}`

// "Jetzt starten" without a stored code: codes are handed out by mail during the test phase.
export function EarlyAccessModal({ onClose, onUnlock }) {
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
        className="impressum-modal early-access-modal"
        onClick={e => e.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="early-access-title"
      >
        <button className="impressum-close" onClick={onClose} aria-label="Schließen">×</button>
        <h2 id="early-access-title">Early Access</h2>
        <p>
          Wir befinden uns aktuell noch in der Testphase. Sie können den Live-Faktencheck aber gerne
          schon vorab nutzen. Schreiben Sie dafür einfach eine kurze Mail
          an <a href={MAILTO}>{CONTACT}</a>. Im Anschluss erhalten Sie einen Zugangscode.
        </p>

        <div className="early-access-code">
          <p className="landing-code-label">Sie haben schon einen Zugangscode?</p>
          <AccessUnlock unlocked={false} onUnlock={onUnlock} />
        </div>
      </div>
    </div>
  )
}
