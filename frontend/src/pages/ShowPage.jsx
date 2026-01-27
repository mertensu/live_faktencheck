import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { BACKEND_URL, getFetchHeaders, safeJsonParse, debug } from '../services/api'
import { FactCheckPage } from './FactCheckPage'

export function ShowPage({ showKey }) {
  const { episode: episodeFromUrl } = useParams()
  const navigate = useNavigate()
  const [episodes, setEpisodes] = useState([])
  const [selectedEpisode, setSelectedEpisode] = useState(null)
  const [showName, setShowName] = useState(showKey.charAt(0).toUpperCase() + showKey.slice(1))

  // Load episodes for this show
  useEffect(() => {
    const controller = new AbortController()
    const defaultShowName = showKey.charAt(0).toUpperCase() + showKey.slice(1)

    const loadEpisodes = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows/${showKey}/episodes`, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })
        if (response.ok) {
          const data = await safeJsonParse(response, 'Error loading episodes')
          const episodesList = data.episodes || []
          setEpisodes(episodesList)

          // Set first episode as default or the one from URL
          if (episodeFromUrl) {
            const found = episodesList.find(e => e.key === episodeFromUrl)
            if (found) {
              setSelectedEpisode(found.key)
              setShowName(found.config.name || defaultShowName)
            } else if (episodesList.length > 0) {
              setSelectedEpisode(episodesList[0].key)
              setShowName(episodesList[0].config.name || defaultShowName)
            }
          } else if (episodesList.length > 0) {
            setSelectedEpisode(episodesList[0].key)
            setShowName(episodesList[0].config.name || defaultShowName)
            // Navigate to first episode (with React Router, respects basename)
            navigate(`/${showKey}/${episodesList[0].key}`, { replace: true })
          }
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          debug.error('Error loading episodes:', error)
        }
      }
    }
    loadEpisodes()

    return () => controller.abort()
  }, [showKey, episodeFromUrl, navigate])

  const handleEpisodeChange = (episodeKey) => {
    setSelectedEpisode(episodeKey)
    const episode = episodes.find(e => e.key === episodeKey)
    if (episode) {
      setShowName(episode.config.name || showName)
      // Navigate with React Router (respects basename)
      navigate(`/${showKey}/${episodeKey}`, { replace: true })
    }
  }

  if (!selectedEpisode) {
    return <div>Lade Episoden...</div>
  }

  return (
    <>
      <div className="episode-selector">
        <label className="episode-selector-label">
          Episode auswahlen:
        </label>
        <select
          value={selectedEpisode}
          onChange={(e) => handleEpisodeChange(e.target.value)}
          className="episode-selector-select"
        >
          {episodes.map(episode => (
            <option key={episode.key} value={episode.key}>
              {episode.name}
            </option>
          ))}
        </select>
      </div>
      <FactCheckPage
        showName={showName}
        showKey={showKey}
        episodeKey={selectedEpisode}
      />
    </>
  )
}
