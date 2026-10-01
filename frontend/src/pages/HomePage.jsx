import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AccessUnlock } from '../components/AccessUnlock'
import { LimitInfoModal } from '../components/LimitInfoModal'
import { LandingIllustration } from '../components/LandingIllustration'
import { getAccessCode } from '../services/api'

function ActionCard({ to, icon, title, description, beta, unlocked, onLockedClick }) {
  const inner = (
    <>
      <div className="action-card-head">
        <span className="action-card-icon" aria-hidden="true">{icon}</span>
        <span className="action-card-title">{title}</span>
        {beta && <span className="beta-tag">beta</span>}
        {!unlocked && <span className="action-card-lock" aria-hidden="true">🔒</span>}
      </div>
      <p className="action-card-desc">{description}</p>
    </>
  )

  if (unlocked) {
    return <Link to={to} className="action-card">{inner}</Link>
  }
  return (
    <button
      type="button"
      className="action-card action-card--locked"
      aria-disabled="true"
      onClick={onLockedClick}
    >
      {inner}
    </button>
  )
}

export function HomePage() {
  const [unlocked, setUnlocked] = useState(Boolean(getAccessCode()))
  const [name, setName] = useState(null)
  const [limitInfo, setLimitInfo] = useState(null)
  const unlockRef = useRef(null)

  const handleUnlock = useCallback((_code, unlockedName, data) => {
    setUnlocked(true)
    setName(unlockedName)
    // Only show the limit popup on an active code entry (data present),
    // not on auto-unlock from a stored code on page reload.
    if (data) setLimitInfo(data)
  }, [])

  const focusUnlock = () => unlockRef.current?.focus()

  return (
    <div className="home-page landing">
      {limitInfo && (
        <LimitInfoModal info={limitInfo} onClose={() => setLimitInfo(null)} />
      )}
      <section className="landing-hero">
        <div className="landing-copy">
          <h1 className="landing-title">Fakten prüfen,<br /> <span className="landing-title-line">während gesprochen wird.</span></h1>
          <div className="landing-lead">
            <p><strong>KI-gestützte Faktenchecks</strong> zu Politik, Wirtschaft und Gesellschaft in Deutschland.</p>
            <p className="landing-lead-muted">
              Ob Talkshow, Interview oder Debatte: Jede überprüfbare Aussage wird live markiert und mit
              vertrauenswürdigen Quellen bewertet, in wenigen Sekunden.
            </p>
          </div>
          <ul className="landing-steps" aria-label="Ablauf">
            <li>Zuhören</li>
            <li>Aussage erkennen</li>
            <li>Quellen prüfen</li>
            <li>Bewerten</li>
          </ul>

          <AccessUnlock
            ref={unlockRef}
            unlocked={unlocked}
            name={name}
            onUnlock={handleUnlock}
          />

          <section className="action-cards action-cards--single">
            <ActionCard
              to="/mein-bereich"
              icon="🎙"
              title="Mein Bereich"
              description="Gespräche live prüfen und deine bisherigen Checks ansehen."
              unlocked={unlocked}
              onLockedClick={focusUnlock}
            />
          </section>
          {!unlocked && (
            <p className="landing-hint">Ohne Code: frühere Checks unter <Link to="/beispiele">Beispiele</Link>.</p>
          )}
        </div>
        <LandingIllustration />
      </section>
    </div>
  )
}
