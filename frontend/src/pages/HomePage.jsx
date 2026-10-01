import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { AccessUnlock } from '../components/AccessUnlock'
import { LimitInfoModal } from '../components/LimitInfoModal'
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
    <div className="home-page">
      {limitInfo && (
        <LimitInfoModal info={limitInfo} onClose={() => setLimitInfo(null)} />
      )}
      <section className="hero-section">
        <h1 className="hero-title">Live-Faktencheck</h1>
        <p className="hero-subtitle">KI-gestützte Faktenchecks zu Politik, Wirtschaft und Gesellschaft in Deutschland.</p>
      </section>

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
          description="Sendungen live prüfen und deine bisherigen Checks ansehen."
          unlocked={unlocked}
          onLockedClick={focusUnlock}
        />
      </section>
    </div>
  )
}
