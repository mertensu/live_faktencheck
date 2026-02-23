import { Link } from 'react-router-dom'
import { useShows } from '../hooks/useShows'

function getEpisodeDisplayName(show) {
  if (typeof show === 'object') {
    if (show.episode_name) return `${show.name} - ${show.episode_name}`
    if (show.name) return show.name
  }
  if (typeof show === 'string') return show.charAt(0).toUpperCase() + show.slice(1)
  return 'Unknown Show'
}

export function HomePage() {
  const { shows, loading } = useShows()
  const isProduction = import.meta.env.PROD

  // Production: show only published episodes
  if (isProduction) {
    const publishedShows = shows.filter(s => s.publish)
    return (
      <div className="home-page">
        <section className="hero-section">
          <h1 className="hero-title">Live-Faktencheck</h1>
          <p className="hero-subtitle">KI-gestützte Faktenchecks in Echtzeit</p>
          {loading ? (
            <div className="loading-container">
              <div className="loading-spinner"></div>
            </div>
          ) : publishedShows.length > 0 ? (
            <section className="shows-section">
              <div className="shows-list">
                {publishedShows.map(show => {
                  const episodeKey = show.key || show
                  const showInfo = show.info || show.description || ""
                  return (
                    <Link key={episodeKey} to={`/${episodeKey}`} className="show-item">
                      <div className="show-item-content">
                        <span className="show-name">{getEpisodeDisplayName(show)}</span>
                        {showInfo && <span className="show-info">{showInfo}</span>}
                      </div>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </Link>
                  )
                })}
              </div>
            </section>
          ) : (
            <div className="coming-soon-badge">
              Coming soon
            </div>
          )}
        </section>
      </div>
    )
  }

  return (
    <div className="home-page">
      {/* Hero Section */}
      <section className="hero-section">
        <h1 className="hero-title">Fakten-Check Live</h1>
        <p className="hero-subtitle">Ein Live-Ticker fur Fakten</p>
        <div className="scroll-indicator">
          <span>Scroll fur aktuelle Checks</span>
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
            <path d="M12 5v14M19 12l-7 7-7-7" />
          </svg>
        </div>
      </section>

      {/* Shows Section */}
      <section className="shows-section">
        {loading ? (
          <div className="loading-container">
            <div className="loading-spinner"></div>
            <p>Sendungen werden geladen...</p>
          </div>
        ) : (
          <>
            {/* TV Shows Group */}
            <div className="shows-group mb-5">
              <h2 className="shows-section-title">TV Talkshows</h2>
              <div className="shows-list">
                {shows.filter(s => (s.key || s) !== 'test' && (!s.type || s.type === 'show')).map(show => {
                  const episodeKey = show.key || show
                  const showInfo = show.info || show.description || ""

                  return (
                    <Link key={episodeKey} to={`/${episodeKey}`} className="show-item">
                      <div className="show-item-content">
                        <span className="show-name">{getEpisodeDisplayName(show)}</span>
                        {showInfo && <span className="show-info">{showInfo}</span>}
                      </div>
                      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                        <path d="M9 18l6-6-6-6" />
                      </svg>
                    </Link>
                  )
                })}
              </div>
            </div>

            {/* YouTube Group */}
            {shows.some(s => s.type === 'youtube') && (
              <div className="shows-group">
                <h2 className="shows-section-title">YouTube-Videos</h2>
                <div className="shows-list">
                  {shows.filter(s => s.type === 'youtube').map(show => {
                    const episodeKey = show.key || show
                    const showInfo = show.info || show.description || ""

                    return (
                      <Link key={episodeKey} to={`/${episodeKey}`} className="show-item">
                        <div className="show-item-content">
                          {showInfo && <span className="show-info">{showInfo}</span>}
                        </div>
                        <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                          <path d="M9 18l6-6-6-6" />
                        </svg>
                      </Link>
                    )
                  })}
                </div>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  )
}
