import { useState, useEffect } from 'react'
import { BACKEND_URL, getFetchHeaders, safeJsonParse, debug } from '../services/api'

const DEFAULT_SHOWS = []

export function useShows() {
  const [shows, setShows] = useState(DEFAULT_SHOWS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()

    const loadShows = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows`, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })
        if (response.ok) {
          const data = await safeJsonParse(response, 'Error loading shows')
          if (data.shows && data.shows.length > 0) {
            setShows(data.shows)
          }
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
