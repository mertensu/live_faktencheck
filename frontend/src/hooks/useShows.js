import { useState, useEffect } from 'react'
import { BACKEND_URL, getFetchHeaders, safeJsonParse, debug } from '../services/api'

const DEFAULT_SHOWS = []

export function useShows() {
  const [shows, setShows] = useState(DEFAULT_SHOWS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    const controller = new AbortController()

    const isLocalhost = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
    const isStaticMode = import.meta.env.PROD && !isLocalhost

    const loadShows = async () => {
      try {
        let data
        if (isStaticMode) {
          const response = await fetch('/data/shows.json', { signal: controller.signal })
          if (response.ok) {
            data = await response.json()
          }
        } else {
          const response = await fetch(`${BACKEND_URL}/api/config/shows`, {
            headers: getFetchHeaders(),
            signal: controller.signal
          })
          if (response.ok) {
            data = await safeJsonParse(response, 'Error loading shows')
          }
        }
        if (data?.shows?.length > 0) {
          setShows(data.shows)
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
