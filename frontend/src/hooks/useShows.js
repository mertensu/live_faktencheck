import { useState, useEffect } from 'react'
import { BACKEND_URL, FETCH_HEADERS, safeJsonParse, debug, isStaticMode } from '../services/api'

export function useShows() {
  const [shows, setShows] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()

    const loadShows = async () => {
      try {
        let data
        if (isStaticMode) {
          const response = await fetch('/data/shows.json', { signal: controller.signal })
          if (!response.ok) throw new Error(`Failed to load shows: ${response.status}`)
          data = await response.json()
        } else {
          const response = await fetch(`${BACKEND_URL}/api/config/shows`, {
            headers: FETCH_HEADERS,
            signal: controller.signal
          })
          if (!response.ok) throw new Error(`Failed to load shows: ${response.status}`)
          data = await safeJsonParse(response, 'Error loading shows')
        }
        if (data?.shows?.length > 0) {
          // Check if backend is live to mark current episode
          let liveKey = null
          try {
            const healthRes = await fetch(`${BACKEND_URL}/api/health`, { signal: controller.signal })
            if (healthRes.ok) {
              const health = await healthRes.json()
              liveKey = health.current_episode || null
            }
          } catch {
            // Backend not running — no live badge
          }
          setShows(liveKey
            ? data.shows.map(s => s.key === liveKey ? { ...s, live: true } : s)
            : data.shows
          )
        }
        setError(null)
      } catch (err) {
        if (err.name !== 'AbortError') {
          debug.error('Error loading shows:', err)
          setError(err)
        }
      } finally {
        if (!controller.signal.aborted) {
          setLoading(false)
        }
      }
    }

    loadShows()

    return () => controller.abort()
  }, [])

  return { shows, loading, error }
}
