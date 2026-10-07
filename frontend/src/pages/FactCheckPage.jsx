import { useState, useEffect, useRef, useCallback } from 'react'
import { BACKEND_URL, authHeaders, safeJsonParse, debug, getAccessCode } from '../services/api'
import { BackendErrorDisplay } from '../components/BackendErrorDisplay'
import { FactCheckStream } from '../components/FactCheckStream'
import { LiveTranscript } from '../components/LiveTranscript'
import { LiveTutorial } from '../components/LiveTutorial'
import { MicSelect } from '../components/MicSelect'
import { ShareLink } from '../components/ShareLink'
import { useAudioStream } from '../hooks/useAudioStream'
import { useMicDevices } from '../hooks/useMicDevices'
import { useSidebar } from '../components/MyChecksSidebar'

// Default speakers as fallback
const DEFAULT_SPEAKERS = []

export function FactCheckPage({ showName, showKey, episodeKey }) {
  // A viewer opened the shared link without an access code: strip the page down
  // to the debate name and the stream — no "Fakten-Check -" prefix, no controls.
  const isViewer = !getAccessCode()

  const [factChecks, setFactChecks] = useState([])
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Load config from backend
  const [displayTitle, setDisplayTitle] = useState(showName)  // Full show title (updated from config)
  const [backendError, setBackendError] = useState(null)  // Backend connection error
  const [notFound, setNotFound] = useState(false)  // session unknown or deleted (config 404)
  // Only surface a connection error after several *consecutive* failed polls.
  // A single transient blip (load race, one slow request tripping the 5s abort)
  // self-heals on the next 2s poll, so showing it immediately just flashes a
  // scary box for one cycle. Reset to 0 on any success.
  const pollFailuresRef = useRef(0)
  const POLL_FAILURE_THRESHOLD = 3  // ~6s of continuous failure before we alarm

  const mic = useMicDevices()
  const liveStream = useAudioStream(episodeKey, { deviceId: mic.deviceId })
  const isLive = liveStream.status === 'streaming' || liveStream.status === 'connecting'
  // The "Meine Checks" sidebar folds to a rail while live, so the transcript gets the width.
  const { setLive: setSidebarLive } = useSidebar()
  useEffect(() => {
    setSidebarLive(isLive)
    return () => setSidebarLive(false)
  }, [isLive, setSidebarLive])
  // Mirrors LiveTranscript's own visibility: a live session is running or left a transcript.
  const showLiveTranscript = !isViewer && (
    isLive || liveStream.transcript.length > 0 || liveStream.claims.length > 0
  )
  // The live-check guide opens every time an operator opens a session that has no
  // results yet (before the show starts) — not when reopening a finished check.
  // Decided once, after the first results fetch, so it doesn't flash open.
  const [tutorialOpen, setTutorialOpen] = useState(false)
  const tutorialDecidedRef = useRef(false)
  const closeTutorial = useCallback(() => setTutorialOpen(false), [])

  // Load episode configuration from backend
  useEffect(() => {
    const controller = new AbortController()
    setNotFound(false)

    const loadEpisodeConfig = async () => {
      const key = episodeKey || showKey || showName.toLowerCase()
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/${key}`, {
          headers: authHeaders(),
          signal: controller.signal
        })
        if (response.ok) {
          const config = await safeJsonParse(response, `Error loading config for ${key}`)
          if (config.speakers && config.speakers.length > 0) {
            setSpeakers(config.speakers)
            debug.log(`Config loaded for ${key}:`, config)
          } else {
            debug.warn(`No speakers in config for ${key}, using fallback`)
          }
          if (config.show_name && config.date) {
            setDisplayTitle(`${config.show_name} vom ${config.date}`)
          } else if (config.show_name) {
            setDisplayTitle(config.show_name)
          }
        } else if (response.status === 404) {
          setNotFound(true)
        } else {
          debug.warn(`Could not load config for ${key}, using fallback`)
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          debug.error(`Error loading config for ${key}:`, error)
        }
      }
    }

    loadEpisodeConfig()

    return () => controller.abort()
  }, [showName, showKey, episodeKey])

  // Polling for fact-checks (only when backend is available)
  useEffect(() => {
    let isMounted = true
    let currentController = null
    tutorialDecidedRef.current = false

    const fetchFactChecks = async () => {
      const controller = new AbortController()
      currentController = controller

      try {
        // Never fetch without a session scope — an unscoped request would return
        // every session's fact-checks. No episode => nothing to show.
        if (!episodeKey) {
          setFactChecks([])
          return
        }
        const url = `${BACKEND_URL}/api/fact-checks?session_id=${episodeKey}`

        debug.log(`Loading fact-checks from: ${url}`)

        // Timeout: abort after 5 seconds
        const timeoutId = setTimeout(() => controller.abort(), 5000)

        const response = await fetch(url, {
          headers: authHeaders(),
          signal: controller.signal
        })

        clearTimeout(timeoutId)

        if (!isMounted) return

        debug.log(`Response Status: ${response.status} ${response.statusText}`)

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await safeJsonParse(response, 'Error loading fact-checks')
        debug.log(`Loaded fact-checks (Live): ${data.length}`, data)
        const visible = data.filter((fc) => fc.status !== 'discarded')
        setFactChecks(visible)
        if (!tutorialDecidedRef.current) {
          tutorialDecidedRef.current = true
          if (!isViewer && visible.length === 0) setTutorialOpen(true)
        }
        pollFailuresRef.current = 0
        setBackendError(null)  // Clear error on success
      } catch (error) {
        if (!isMounted) return

        pollFailuresRef.current += 1
        const message = error.name === 'AbortError'
          ? 'Backend request timed out'
          : (error.message || 'Unknown error')
        if (error.name !== 'AbortError') {
          debug.error('Error loading from backend:', error)
        }

        // Tolerate transient failures: only alarm (and blank the results) once
        // failures pile up. Below the threshold we keep the last-known list and
        // stay silent, so a single blip is invisible to the viewer.
        if (pollFailuresRef.current >= POLL_FAILURE_THRESHOLD) {
          setBackendError({
            message,
            backendUrl: BACKEND_URL,
            episodeKey: episodeKey
          })
          setFactChecks([])  // Clear fact checks on sustained error
        }
      }
    }

    fetchFactChecks()
    const interval = setInterval(fetchFactChecks, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [episodeKey, isViewer])

  // What sits below the header when no live transcript is showing:
  // - viewer: the results stream, or a "starts soon" note until the first result
  // - operator on a session with results (e.g. a Beispiel): the read-only stream
  // - operator before going live: share link + mic picker; the header starts Live-Check
  const renderResults = () => {
    if (notFound) {
      return (
        <div className="review-view">
          <div className="review-waiting-live" role="status">
            <p className="review-waiting-title">Diesen Faktencheck gibt es nicht (mehr)</p>
            <p className="review-waiting-sub">
              Der Link ist falsch, oder der Check wurde gelöscht.
            </p>
          </div>
        </div>
      )
    }
    if (factChecks.length > 0) {
      return (
        <div className="review-view">
          <FactCheckStream factChecks={factChecks} />
        </div>
      )
    }
    if (isViewer) {
      return (
        <div className="review-view">
          <div className="review-waiting-live" role="status">
            <span className="review-waiting-pulse" aria-hidden="true" />
            <p className="review-waiting-title">Live-Faktencheck startet in Kürze</p>
            <p className="review-waiting-sub">
              Sobald geprüfte Aussagen vorliegen, erscheinen sie hier automatisch.
            </p>
          </div>
        </div>
      )
    }
    return (
      <div className="review-view">
        <ShareLink sessionId={episodeKey} />
        <div className="review-start">
          <MicSelect mic={mic} className="review-start-mic" />
          <p className="review-start-info">
            Mit <strong>◉ Live-Check</strong> oben starten Sie Transkript und Prüfung.
          </p>
        </div>
      </div>
    )
  }

  return (
    <>
      <header className="app-header">
        <div className="factcheck-header-content">
          <div>
            <h1>{isViewer ? displayTitle : `Fakten-Check - ${displayTitle}`}</h1>
          </div>
          {!isViewer && !notFound && (
          <div className="factcheck-header-actions">
            {isLive ? (
              <button type="button" className="header-rec-stop" onClick={() => liveStream.stop()}>
                <span className="header-rec-dot" aria-hidden="true">◉</span>
                {liveStream.status === 'connecting' ? 'Live verbindet…' : 'Live stoppen'}
              </button>
            ) : (
              <button
                type="button"
                className="header-rec-start"
                onClick={() => liveStream.start()}
                title="Live-Check starten (Streaming)"
              >
                ◉ Live-Check
              </button>
            )}
            <button type="button" className="header-help-link" onClick={() => setTutorialOpen(true)}>
              Kurzanleitung
            </button>
            {liveStream.error && (
              <span className="header-live-error">{liveStream.error}</span>
            )}
          </div>
          )}
        </div>
      </header>

      {tutorialOpen && !isViewer && !notFound && <LiveTutorial onClose={closeTutorial} />}
      <main className="main-content">
        {showLiveTranscript && <LiveTranscript live={liveStream} speakers={speakers} />}
        <BackendErrorDisplay error={backendError} />
        {/* In the live view, results open from the transcript marks, not as a list below. */}
        {!showLiveTranscript && renderResults()}
      </main>
    </>
  )
}
