import { useState, useEffect, useRef, useCallback } from 'react'
import { BACKEND_URL, authHeaders, safeJsonParse, debug, getAccessCode } from '../services/api'
import { BackendErrorDisplay } from '../components/BackendErrorDisplay'
import { FactCheckStream } from '../components/FactCheckStream'
import { LiveTranscript } from '../components/LiveTranscript'
import { LiveTutorial } from '../components/LiveTutorial'
import { LiveStartPanel, LiveStartDesktopOnly, isTouchOnly } from '../components/LiveStartPanel'
import { useAudioStream } from '../hooks/useAudioStream'
import { useMicDevices } from '../hooks/useMicDevices'
import { useTabAudio } from '../hooks/useTabAudio'
import { useSidebar } from '../components/MyChecksSidebar'

// Default speakers as fallback
const DEFAULT_SPEAKERS = []

export function FactCheckPage({ showName, showKey, episodeKey }) {
  // A viewer opened the shared link without an access code: strip the page down
  // to the debate name and the stream, no controls.
  const isViewer = !getAccessCode()
  // Phones and mouse-less tablets get no live check (see isTouchOnly); viewing stays open.
  const [touchOnly] = useState(isTouchOnly)

  const [factChecks, setFactChecks] = useState([])
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Load config from backend
  const [excludedSpeakers, setExcludedSpeakers] = useState([])  // named but not checked (e.g. moderation)
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
  const tab = useTabAudio()
  const [audioSource, setAudioSource] = useState('mic')  // 'mic' | 'tab'
  const liveStream = useAudioStream(episodeKey, { deviceId: mic.deviceId })
  // Back to the mic ends a tab share, so the browser's "sharing" bar goes away.
  const chooseAudioSource = useCallback((source) => {
    setAudioSource(source)
    if (source !== 'tab') tab.release()
  }, [tab])
  // A tab is shared on the first start if none was picked yet (the click allows the prompt).
  const startLive = useCallback(async () => {
    if (audioSource !== 'tab') return liveStream.start()
    const stream = tab.stream || await tab.pick()
    if (stream) liveStream.start(stream)
  }, [audioSource, tab, liveStream])
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
  // Before going live the start panel holds the start button (and its error); the
  // header button only resumes a session that already has a transcript or results.
  const showStartPanel = !isViewer && !notFound && !showLiveTranscript && factChecks.length === 0
  // The practice: folded into the start panel before going live; once the panel is gone
  // (live, or a session with results) "Kurzanleitung" opens it as a dialog instead.
  const [practiceOpen, setPracticeOpen] = useState(false)
  const [tutorialOpen, setTutorialOpen] = useState(false)
  const closeTutorial = useCallback(() => setTutorialOpen(false), [])
  const openGuide = useCallback(() => {
    if (!showStartPanel) { setTutorialOpen(true); return }
    setPracticeOpen(true)
    requestAnimationFrame(() => document.getElementById('live-practice')?.scrollIntoView?.({ block: 'start', behavior: 'smooth' }))
  }, [showStartPanel])

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
          setExcludedSpeakers(config.excluded_speakers || [])
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
  }, [episodeKey])

  // What sits below the header when no live transcript is showing:
  // - viewer: the results stream, or a "starts soon" note until the first result
  // - operator on a session with results (e.g. a Beispiel): the read-only stream
  // - operator before going live: the start panel (sound check, people, start, share link)
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
    if (touchOnly) return <LiveStartDesktopOnly />
    return (
      <LiveStartPanel
        sessionId={episodeKey}
        mic={mic}
        tab={tab}
        audioSource={audioSource}
        onAudioSource={chooseAudioSource}
        speakers={speakers}
        excludedSpeakers={excludedSpeakers}
        onStart={startLive}
        connecting={liveStream.status === 'connecting'}
        error={liveStream.error}
        practiceOpen={practiceOpen}
        onPracticeOpen={setPracticeOpen}
      />
    )
  }

  return (
    <>
      <header className="app-header">
        <div className="factcheck-header-content">
          <div>
            <h1>{displayTitle}</h1>
          </div>
          {!isViewer && !notFound && (
          <div className="factcheck-header-actions">
            {isLive ? (
              <button type="button" className="header-rec-stop" onClick={() => liveStream.stop()}>
                <span className="header-rec-dot" aria-hidden="true">◉</span>
                {liveStream.status === 'connecting' ? 'Live verbindet…' : 'Live stoppen'}
              </button>
            ) : !showStartPanel && !touchOnly && (
              <button
                type="button"
                className="header-rec-start"
                onClick={startLive}
                title="Live-Check starten (Streaming)"
              >
                ◉ Live-Check
              </button>
            )}
            {!touchOnly && (
              <button type="button" className="header-help-link" onClick={openGuide}>
                Kurzanleitung
              </button>
            )}
            {liveStream.error && !showStartPanel && (
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
