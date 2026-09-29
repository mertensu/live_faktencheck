import { Link } from 'react-router-dom'
import { useShows } from '../hooks/useShows'

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

export function ExamplesPage() {
  const { shows, loading } = useShows()

  const visibleShows = shows.filter(s => (s.key || s) !== 'test')

  return (
    <div className="home-page">
      <section className="examples-section">
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
