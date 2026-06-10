import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useShows } from '../hooks/useShows'
import { AccessUnlock } from '../components/AccessUnlock'
import { getAccessCode } from '../services/api'

function getEpisodeDisplayName(show) {
  if (typeof show === 'object') {
    if (show.episode_name) {
      // Strip date prefix from episode_name (format: "DD. Month YYYY - Guests")
      let episodePart = show.episode_name
      if (show.date && episodePart.startsWith(show.date + ' - ')) {
        episodePart = episodePart.slice((show.date + ' - ').length)
      } else if (show.date && episodePart === show.date) {
        episodePart = null
      }
      return episodePart ? `${show.name} - Gäste: ${episodePart}` : show.name
    }
    if (show.name) return show.name
  }
  if (typeof show === 'string') return show.charAt(0).toUpperCase() + show.slice(1)
  return 'Unknown Show'
}

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
  const { shows, loading } = useShows()
  const [unlocked, setUnlocked] = useState(Boolean(getAccessCode()))
  const [name, setName] = useState(null)
  const unlockRef = useRef(null)

  const handleUnlock = useCallback((_code, unlockedName) => {
    setUnlocked(true)
    setName(unlockedName)
  }, [])

  const focusUnlock = () => unlockRef.current?.focus()

  const visibleShows = shows.filter(s => (s.key || s) !== 'test')

  return (
    <div className="home-page">
      <section className="hero-section">
        <h1 className="hero-title">Live-Faktencheck</h1>
        <p className="hero-subtitle">KI-gestützte Einordnung im Minutentakt.</p>
      </section>

      <AccessUnlock
        ref={unlockRef}
        unlocked={unlocked}
        name={name}
        onUnlock={handleUnlock}
      />

      <section className="action-cards">
        <ActionCard
          to="/pruefen"
          icon="🔎"
          title="Behauptung prüfen"
          description="Ein Zitat oder eine Aussage einfügen und sofort einen Faktencheck erhalten."
          unlocked={unlocked}
          onLockedClick={focusUnlock}
        />
        <ActionCard
          to="/new"
          icon="🎙"
          title="Live-Session starten"
          description="Eine Sendung live mitschneiden und Aussagen in Echtzeit prüfen."
          beta
          unlocked={unlocked}
          onLockedClick={focusUnlock}
        />
      </section>

      <section className="examples-section" id="beispiele">
        <h2 className="examples-title">Beispiele</h2>
        <p className="examples-intro">Frühere Faktenchecks als Vertrauensbeleg.</p>
        {loading ? (
          <div className="loading-container">
            <div className="loading-spinner"></div>
          </div>
        ) : visibleShows.length > 0 ? (
          <div className="shows-list">
            {visibleShows.map(show => {
              const episodeKey = show.key || show
              const showInfo = show.date || ''
              return (
                <Link key={episodeKey} to={`/${episodeKey}`} className="show-item">
                  <div className="show-item-content">
                    <div className="show-name-row">
                      <span className="show-name">{getEpisodeDisplayName(show)}</span>
                      {show.live && <span className="live-badge">LIVE</span>}
                    </div>
                    {showInfo && <span className="show-info">{showInfo}</span>}
                  </div>
                  <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                    <path d="M9 18l6-6-6-6" />
                  </svg>
                </Link>
              )
            })}
          </div>
        ) : (
          <div className="coming-soon-badge">Coming soon</div>
        )}
      </section>
    </div>
  )
}
