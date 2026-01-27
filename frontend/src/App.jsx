import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation, useNavigate, useParams } from 'react-router-dom'
import './App.css'

// Konfiguration: Sprecher werden vom Backend geladen (siehe FactCheckPage)
// Fallback-Sprecher falls Backend nicht erreichbar ist
const DEFAULT_SPEAKERS = [
  'Sandra Maischberger',
  'Gitta Connemann',
  'Katharina Dröge'
]

// N8N Webhook URL für verified claims
const N8N_VERIFIED_WEBHOOK = "http://localhost:5678/webhook/verified-claims"

// Debug logging - nur in Entwicklung aktiv
const debug = {
  log: (...args) => { if (import.meta.env.DEV) console.log(...args) },
  warn: (...args) => { if (import.meta.env.DEV) console.warn(...args) },
  error: (...args) => { if (import.meta.env.DEV) console.error(...args) }
}

// Backend URL - wird basierend auf Environment angepasst
const getBackendUrl = () => {
  // In Produktion: Backend URL über Cloudflare Tunnel
  // Setze VITE_BACKEND_URL in .env oder als Environment Variable
  if (import.meta.env.PROD) {
    // Versuche Environment Variable, sonst Fallback auf localhost (für lokale Tests)
    return import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
  }
  // In Entwicklung: localhost
  return 'http://localhost:5000'
}

const BACKEND_URL = getBackendUrl()

// Helper: Erstellt fetch-Headers
const getFetchHeaders = () => {
  return {
    'Accept': 'application/json',
    'Content-Type': 'application/json'
  }
}

// Helper: Prüft ob Response JSON ist (nicht HTML)
const isJsonResponse = (response) => {
  const contentType = response.headers.get('content-type')
  return contentType && contentType.includes('application/json')
}

// Helper: Safe JSON parsing mit Fehlerbehandlung
const safeJsonParse = async (response, errorContext = '') => {
  if (!isJsonResponse(response)) {
    const text = await response.text()
    if (text.trim().startsWith('<!DOCTYPE') || text.includes('<html')) {
      debug.error(`❌ ${errorContext}: Backend antwortet mit HTML statt JSON`)
      debug.error(`   URL: ${response.url}`)
      debug.error(`   Status: ${response.status}`)
      debug.error(`   Response (erste 200 Zeichen): ${text.substring(0, 200)}`)
      throw new Error('Backend antwortet mit HTML statt JSON. Prüfe ob Backend läuft und erreichbar ist.')
    }
  }
  try {
    return await response.json()
  } catch (error) {
    debug.error(`❌ ${errorContext}: Fehler beim Parsen der JSON-Response`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Fehler: ${error.message}`)
    throw error
  }
}

// Markdown regex patterns - compiled once at module load for better performance
const MARKDOWN_BOLD_PATTERN = /\*\*(.+?)\*\*/g
const MARKDOWN_ITALIC_PATTERN = /(?<!\*)\*([^*]+?)\*(?!\*)/g
const MARKDOWN_LINK_PATTERN = /\[([^\]]+)\]\(([^)]+)\)/g

// Custom Hook: Lädt Shows vom Backend (eliminiert Duplikation)
const DEFAULT_SHOWS = ['test', 'maischberger', 'miosga']

function useShows() {
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
          const data = await safeJsonParse(response, 'Fehler beim Laden der Shows')
          if (data.shows && data.shows.length > 0) {
            setShows(data.shows)
          }
        }
        setError(null)
      } catch (err) {
        if (err.name !== 'AbortError') {
          debug.error('❌ Fehler beim Laden der Shows:', err)
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

function App() {
  const { shows } = useShows()

  return (
    <BrowserRouter basename={import.meta.env.PROD ? '/live_faktencheck' : ''}>
      <div className="app">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/about" element={<AboutPage />} />
          <Route path="/test" element={<FactCheckPage showName="Test" showKey="test" episodeKey="test" />} />
          {/* Dynamische Routes für alle Shows */}
          {shows.filter(s => (s.key || s) !== 'test').map(show => {
            const showKey = show.key || show
            return (
              <Route
                key={showKey}
                path={`/${showKey}/:episode?`}
                element={<ShowPage showKey={showKey} />}
              />
            )
          })}
        </Routes>
        <Footer />
      </div>
    </BrowserRouter>
  )
}

// GitHub Repository URL
const GITHUB_REPO_URL = "https://github.com/ulfmertens/fact_check"

function Navigation() {
  const location = useLocation()

  return (
    <nav className="main-navigation">
      <div className="nav-container">
        <Link to="/" className="nav-logo">Fakten-Check Live</Link>
        <div className="nav-links">
          <Link to="/about" className={location.pathname === '/about' ? 'active' : ''}>
            About
          </Link>
          <a
            href={GITHUB_REPO_URL}
            target="_blank"
            rel="noopener noreferrer"
            className="github-link"
            aria-label="GitHub Repository"
          >
            <svg height="24" width="24" viewBox="0 0 16 16" fill="currentColor">
              <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.013 8.013 0 0016 8c0-4.42-3.58-8-8-8z" />
            </svg>
          </a>
        </div>
      </div>
    </nav>
  )
}

// Show name mapping for full display names (Fallback/Legacy)
const SHOW_DISPLAY_NAMES = {
  'test': 'Test',
  'maischberger': 'Maischberger',
  'miosga': 'Caren Miosga',
  'lanz': 'Markus Lanz',
  'illner': 'Maybrit Illner'
}

function getShowDisplayName(show) {
  if (typeof show === 'object' && show.name) return show.name
  if (typeof show === 'string') return SHOW_DISPLAY_NAMES[show] || show.charAt(0).toUpperCase() + show.slice(1)
  return 'Unknown Show'
}

function HomePage() {
  const { shows, loading } = useShows()

  return (
    <div className="home-page">
      {/* Hero Section */}
      <section className="hero-section">
        <h1 className="hero-title">Fakten-Check Live</h1>
        <p className="hero-subtitle">Ein Live-Ticker für Fakten</p>
        <div className="scroll-indicator">
          <span>Scroll für aktuelle Checks</span>
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
                  const showKey = show.key || show
                  const showInfo = show.info || show.description || ""

                  return (
                    <Link key={showKey} to={`/${showKey}`} className="show-item">
                      <div className="show-item-content">
                        <span className="show-name">{getShowDisplayName(show)}</span>
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
                    const showKey = show.key || show
                    const showInfo = show.info || show.description || ""

                    return (
                      <Link key={showKey} to={`/${showKey}`} className="show-item">
                        <div className="show-item-content">
                          {/* name hidden for youtube */}
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

function AboutPage() {
  return (
    <div className="about-page">
      <div className="about-content">
        <h1>Über live-faktencheck.de</h1>
        <p>
          Live-Faktenchecks waren in der Vergangenheit immer wieder Diskussions-Thema. Mit der stetigen Entwicklung bestehender
          KI-Modelle sind wir nun, wie ich finde, an einem Punkt angelangt, der ein solches Projekt realisierbar macht. Dieses Projekt ist mein Versuch,
          einen Live-Faktencheck auf Basis von künstlicher Intelligenz umzusetzen. Das Projekt ist bei Weitem nicht ausgereift und Fehler sind nicht ausgeschlossen.
          Nichtsdestotrotz hoffe ich, dass es für den einen oder anderen interessant sein könnte und eine Hilfestellung darstellt.
          <br />
          Ich möchte betonen, dass es hier ausdrücklich nicht darum geht, die Gäste bzw. Content-Creator an den Pranger zu stellen, zu diskreditieren oder in sonstiger Weise
          in Verruf zu bringen. Es geht vielmehr darum, aufzuzeigen, wie sehr bestimmte Behauptungen durch Studien, Statistiken oder andere vertrauenswürdige Quellen, gestützt werden.
          Somit bleiben die Aussagen nicht undiskutiert im Raume stehen, sondern werden einer (ersten) kritischen Betrachtung unterzogen, und zwar während die Sendung läuft.
        </p>
        <h2>Wie es funktioniert</h2>
        <p>
          Die Sendungen werden in zeitlich begrenzte Blöcke aufgeteilt und dann live transkribiert. Diese Transkripte werden an ein großes Sprachmodell (LLM) weitergereicht,
          welches überprüfbare Behauptungen extrahiert und diese automatisch den jeweiligen Sprechern zuweist. Diese Aussagen werden dann auf Relevanz und Korrektheit geprüft und schließlich
          einem weiteren Agenten (LLM) zur Bewertung übergeben. Das Modell startet daraufhin eine Web-Recherche, wobei es sich auf
          vertrauenswurdige Seiten beschränkt (offizielle Regierungsseiten, anerkannte Institute, etc.). Das Modell nimmt eine Bewertung vor (wie sehr wird die Aussage durch Daten gestützt),
          gibt eine ausführliche Erklärung ab sowie die der Entscheidung zugrundliegenden Quellen an. Für Details sei auf das <a href="https://github.com/mertensu/live_faktencheck">Github-Repository</a> verwiesen.
        </p>
        <h2>Hinweis</h2>
        <p>
          Die hier dargestellten Fakten-Checks werden automatisch mit Hilfe von
          Künstlicher Intelligenz (KI) generiert. Die Inhalte können Fehler enthalten
          und sollten nicht als alleinige Grundlage für Entscheidungen verwendet werden.
        </p>
      </div>
    </div>
  )
}

function ShowPage({ showKey }) {
  const { episode: episodeFromUrl } = useParams()
  const navigate = useNavigate()
  const [episodes, setEpisodes] = useState([])
  const [selectedEpisode, setSelectedEpisode] = useState(null)
  const [showName, setShowName] = useState(showKey.charAt(0).toUpperCase() + showKey.slice(1))

  // Lade Episoden für diese Show
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
          const data = await safeJsonParse(response, 'Fehler beim Laden der Episoden')
          const episodesList = data.episodes || []
          setEpisodes(episodesList)

          // Setze erste Episode als Standard oder die aus der URL
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
            // Navigiere zur ersten Episode (mit React Router, respektiert basename)
            navigate(`/${showKey}/${episodesList[0].key}`, { replace: true })
          }
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          debug.error('❌ Fehler beim Laden der Episoden:', error)
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
      // Navigiere mit React Router (respektiert basename)
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
          Episode auswählen:
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

function FactCheckPage({ showName, showKey, episodeKey }) {
  // Admin-Modus verfügbar wenn:
  // 1. Nicht in Produktion (Entwicklung) ODER
  // 2. Lokal auf localhost (auch bei Production-Build)
  // 3. Wenn ?admin=true in URL
  const searchParams = typeof window !== 'undefined' ? new URLSearchParams(window.location.search) : new URLSearchParams()
  const forceAdmin = searchParams.get('admin') === 'true'

  const isProduction = import.meta.env.PROD
  const isLocalhost = typeof window !== 'undefined' &&
    (window.location.hostname === 'localhost' ||
      window.location.hostname === '127.0.0.1' ||
      window.location.hostname.startsWith('192.168.'))
  const showAdminMode = !isProduction || isLocalhost || forceAdmin

  const [isAdminMode, setIsAdminMode] = useState(false)
  const [factChecks, setFactChecks] = useState([])
  const [expandedIds, setExpandedIds] = useState(new Set())
  // Admin workflow: flat list → staging → sent history
  const [pendingClaims, setPendingClaims] = useState([])   // Flat list of editable claims
  const [stagedClaims, setStagedClaims] = useState([])     // Ready to send (read-only)
  const [sentClaims, setSentClaims] = useState([])         // History with timestamps
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Lädt Config vom Backend
  const [backendError, setBackendError] = useState(null)  // Backend connection error

  // Helper: Flatten pending blocks into chronologically sorted claims
  const flattenPendingBlocks = (blocks) => {
    const claims = []
    blocks.forEach(block => {
      block.claims.forEach((claim, index) => {
        claims.push({
          id: `${block.block_id}-${index}`,
          blockId: block.block_id,
          name: claim.name || '',
          claim: claim.claim || '',
          timestamp: block.timestamp,
          info: block.info || block.headline || ''
        })
      })
    })
    // Sort by timestamp (oldest first)
    return claims.sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
  }

  // Lade Episode-Konfiguration vom Backend
  useEffect(() => {
    const controller = new AbortController()

    const loadEpisodeConfig = async () => {
      // Verwende episodeKey (z.B. "maischberger-2025-09-19") oder showKey als Fallback
      const key = episodeKey || showKey || showName.toLowerCase()
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/${key}`, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })
        if (response.ok) {
          const config = await safeJsonParse(response, `Fehler beim Laden der Config für ${key}`)
          if (config.speakers && config.speakers.length > 0) {
            setSpeakers(config.speakers)
            debug.log(`✅ Config geladen für ${key}:`, config)
          } else {
            debug.warn(`⚠️ Keine Sprecher in Config für ${key}, verwende Fallback`)
          }
        } else {
          debug.warn(`⚠️ Konnte Config nicht laden für ${key}, verwende Fallback`)
        }
      } catch (error) {
        if (error.name !== 'AbortError') {
          debug.error(`❌ Fehler beim Laden der Config für ${key}:`, error)
        }
      }
    }

    loadEpisodeConfig()

    return () => controller.abort()
  }, [showName, showKey, episodeKey])

  // Polling für Fact-Checks (nur im normalen Modus)
  useEffect(() => {
    if (isAdminMode) return

    let isMounted = true
    let currentController = null

    const fetchFactChecks = async () => {
      // Erstelle neuen Controller für jeden Fetch-Aufruf
      const controller = new AbortController()
      currentController = controller

      try {
        const url = episodeKey
          ? `${BACKEND_URL}/api/fact-checks?episode=${episodeKey}`
          : `${BACKEND_URL}/api/fact-checks`

        debug.log(`🔍 Lade Fact-Checks von: ${url}`)
        debug.log(`   Backend URL: ${BACKEND_URL}`)
        debug.log(`   Episode Key: ${episodeKey}`)

        // Timeout: Abbruch nach 5 Sekunden
        const timeoutId = setTimeout(() => controller.abort(), 5000)

        const response = await fetch(url, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })

        clearTimeout(timeoutId)

        // Prüfe ob Komponente noch gemountet ist
        if (!isMounted) return

        debug.log(`📡 Response Status: ${response.status} ${response.statusText}`)

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const data = await safeJsonParse(response, 'Fehler beim Laden der Fakten-Checks')
        debug.log(`✅ Geladene Fakten-Checks (Live): ${data.length}`, data)
        setFactChecks(data)
        setBackendError(null)  // Clear error on success
      } catch (error) {
        // Ignoriere Fehler wenn Komponente nicht mehr gemountet
        if (!isMounted) return

        if (error.name === 'AbortError') {
          setBackendError({
            message: 'Backend-Anfrage hat zu lange gedauert (Timeout)',
            backendUrl: BACKEND_URL,
            episodeKey: episodeKey
          })
        } else {
          debug.error('❌ Fehler beim Laden vom Backend:', error)
          debug.error(`   Backend URL: ${BACKEND_URL}`)
          debug.error(`   Episode Key: ${episodeKey}`)
          setBackendError({
            message: error.message || 'Unbekannter Fehler',
            backendUrl: BACKEND_URL,
            episodeKey: episodeKey
          })
        }
        setFactChecks([])  // Clear fact checks on error
      }
    }

    fetchFactChecks()
    // Polling in allen Umgebungen (auch Produktion für Live-Updates)
    const interval = setInterval(fetchFactChecks, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [isAdminMode, episodeKey])

  // Polling für Pending Claims (nur im Admin-Modus und nur lokal)
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return

    let isMounted = true
    let currentController = null

    const fetchPendingClaimsFromBackend = async () => {
      const controller = new AbortController()
      currentController = controller

      try {
        const response = await fetch(`${BACKEND_URL}/api/pending-claims`, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })

        if (!isMounted) return

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        const data = await safeJsonParse(response, 'Fehler beim Laden der Pending Claims')
        debug.log(`📋 Geladene Pending Blocks: ${data.length}`, data)

        // Flatten blocks into claims, excluding those already staged or sent
        const flatClaims = flattenPendingBlocks(data)
        const stagedIds = new Set(stagedClaims.map(c => c.id))
        const sentIds = new Set(sentClaims.map(c => c.originalId || c.id))
        const newPending = flatClaims.filter(c => !stagedIds.has(c.id) && !sentIds.has(c.id))
        setPendingClaims(newPending)
      } catch (error) {
        if (!isMounted || error.name === 'AbortError') return
        debug.error('❌ Fehler beim Laden der Pending Claims:', error)
      }
    }

    fetchPendingClaimsFromBackend()
    const interval = setInterval(fetchPendingClaimsFromBackend, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [isAdminMode, isProduction, stagedClaims, sentClaims])

  const toggleExpand = (id) => {
    const newExpanded = new Set(expandedIds)
    if (newExpanded.has(id)) {
      newExpanded.delete(id)
    } else {
      newExpanded.add(id)
    }
    setExpandedIds(newExpanded)
  }

  // Move claim from pending → staging (with current edits)
  const stageClaimForSending = (claimId) => {
    const claim = pendingClaims.find(c => c.id === claimId)
    if (!claim) return
    setStagedClaims(prev => [...prev, { ...claim }])
    setPendingClaims(prev => prev.filter(c => c.id !== claimId))
  }

  // Move claim from staging → pending (for further editing)
  const unstageClaim = (claimId) => {
    const claim = stagedClaims.find(c => c.id === claimId)
    if (!claim) return
    setPendingClaims(prev => [...prev, { ...claim }].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)))
    setStagedClaims(prev => prev.filter(c => c.id !== claimId))
  }

  // Edit claim in pending list
  const updatePendingClaim = (claimId, field, value) => {
    setPendingClaims(prev => prev.map(c =>
      c.id === claimId ? { ...c, [field]: value } : c
    ))
  }

  // Send all staged claims to backend for fact-checking
  const sendStagedClaims = async () => {
    if (stagedClaims.length === 0) {
      alert('Keine Claims zum Senden ausgewählt!')
      return
    }

    // Separate new claims from re-sends
    const newClaims = stagedClaims.filter(c => !c.originalFactCheckId)
    const resendClaims = stagedClaims.filter(c => c.originalFactCheckId)

    try {
      const results = []

      // Send new claims via POST
      if (newClaims.length > 0) {
        const claimsToSend = newClaims.map(c => ({
          name: c.name,
          claim: c.claim
        }))

        const response = await fetch(`${BACKEND_URL}/api/approve-claims`, {
          method: 'POST',
          headers: getFetchHeaders(),
          body: JSON.stringify({
            block_id: `staged_${Date.now()}`,
            claims: claimsToSend,
            n8n_webhook_url: N8N_VERIFIED_WEBHOOK
          })
        })

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }

        const result = await safeJsonParse(response, 'Fehler beim Senden der neuen Claims')
        debug.log('✅ Neue Claims gesendet:', result)
        results.push(`${newClaims.length} neue Claims`)
      }

      // Send re-sends via PUT (overwrite existing fact-checks)
      for (const claim of resendClaims) {
        const response = await fetch(`${BACKEND_URL}/api/fact-checks/${claim.originalFactCheckId}`, {
          method: 'PUT',
          headers: getFetchHeaders(),
          body: JSON.stringify({
            name: claim.name,
            claim: claim.claim
          })
        })

        if (!response.ok) {
          debug.warn(`⚠️ Fehler beim Re-send für ID ${claim.originalFactCheckId}:`, response.status)
        } else {
          debug.log(`✅ Re-send für ID ${claim.originalFactCheckId} gestartet`)
        }
      }
      if (resendClaims.length > 0) {
        results.push(`${resendClaims.length} Re-sends`)
      }

      // Move staged claims to sent history with timestamp
      const sentTimestamp = new Date().toISOString()
      const newSentClaims = stagedClaims.map(c => ({
        ...c,
        originalId: c.id,
        sentAt: sentTimestamp,
        factCheckId: c.originalFactCheckId || null
      }))
      setSentClaims(prev => [...newSentClaims, ...prev])
      setStagedClaims([])

      alert(`✅ Erfolgreich gesendet: ${results.join(', ')}`)
    } catch (error) {
      debug.error('❌ Fehler beim Senden:', error)
      alert(`❌ Fehler beim Senden: ${error.message}`)
    }
  }

  // Copy sent claim back to pending for editing and re-send
  const prepareResend = (claimId) => {
    const claim = sentClaims.find(c => c.id === claimId || c.originalId === claimId)
    if (!claim) return

    // Create a new claim in pending with reference to original
    const resendClaim = {
      id: `resend_${Date.now()}_${claim.originalId || claim.id}`,
      blockId: claim.blockId,
      name: claim.name,
      claim: claim.claim,
      timestamp: new Date().toISOString(),
      info: claim.info,
      resendOf: claim.originalId || claim.id,
      originalFactCheckId: claim.factCheckId
    }
    setPendingClaims(prev => [resendClaim, ...prev])
  }

  // Gruppiere Fakten-Checks nach Sprecher
  // Unterstützt exakte Übereinstimmung und Teilübereinstimmung (z.B. "Connemann" passt zu "Gitta Connemann")
  const groupedBySpeaker = speakers.reduce((acc, speaker) => {
    acc[speaker] = factChecks.filter(fc => {
      const factCheckSpeaker = fc.sprecher || ''
      // Exakte Übereinstimmung
      if (factCheckSpeaker === speaker) return true
      // Teilübereinstimmung: Wenn der Config-Sprecher den Fact-Check-Sprecher enthält oder umgekehrt
      if (speaker.includes(factCheckSpeaker) || factCheckSpeaker.includes(speaker)) return true
      return false
    })
    return acc
  }, {})

  return (
    <>
      <header className="app-header">
        <div className="factcheck-header-content">
          <div>
            <h1>Fakten-Check - {showName}</h1>
            <p className="subtitle">{isAdminMode ? 'Admin-Modus: Claim-Überprüfung' : 'Live Fact-Checking Dashboard'}</p>
          </div>
          {showAdminMode && (
            <button
              className="admin-toggle"
              onClick={() => setIsAdminMode(!isAdminMode)}
            >
              {isAdminMode ? '👤 Normal-Modus' : '⚙️ Admin-Modus'}
            </button>
          )}
        </div>
      </header>

      <main className="main-content">
        {isAdminMode ? (
          <AdminView
            pendingClaims={pendingClaims}
            stagedClaims={stagedClaims}
            sentClaims={sentClaims}
            onStage={stageClaimForSending}
            onUnstage={unstageClaim}
            onUpdatePending={updatePendingClaim}
            onSendAll={sendStagedClaims}
            onResend={prepareResend}
          />
        ) : (
          <>
            <BackendErrorDisplay error={backendError} />
            <SpeakerColumns
              speakers={speakers}
              groupedBySpeaker={groupedBySpeaker}
              expandedIds={expandedIds}
              onToggle={toggleExpand}
            />
          </>
        )}
      </main>
    </>
  )
}

function BackendErrorDisplay({ error }) {
  if (!error) return null

  return (
    <div className="backend-error">
      <h3 className="backend-error-title">❌ Backend-Verbindungsfehler</h3>
      <p className="backend-error-message">{error.message}</p>
      <details className="backend-error-details">
        <summary>Details</summary>
        <div className="backend-error-info">
          <p><strong>Backend URL:</strong> {error.backendUrl}</p>
          <p><strong>Episode:</strong> {error.episodeKey || 'N/A'}</p>
          <p className="backend-error-hint">
            Bitte überprüfe, ob das Backend läuft und die URL korrekt ist.
          </p>
        </div>
      </details>
    </div>
  )
}

function SpeakerColumns({ speakers, groupedBySpeaker, expandedIds, onToggle }) {
  return (
    <>
      {/* Sprecher Header - nebeneinander */}
      <div className="speakers-container">
        {speakers.map((speaker) => {
          const count = groupedBySpeaker[speaker]?.length || 0
          return (
            <div key={speaker} className="speaker-column">
              <div className="speaker-header">
                <h2>{speaker}</h2>
                <span className="claim-count">{count} Behauptung{count !== 1 ? 'en' : ''}</span>
              </div>
            </div>
          )
        })}
      </div>

      {/* Behauptungen unter den Sprechern */}
      <div className="claims-container">
        {speakers.map((speaker) => {
          const claims = groupedBySpeaker[speaker] || []
          return (
            <div key={speaker} className="speaker-claims-column">
              {claims.length === 0 ? (
                <div className="no-claims">Noch keine Behauptungen</div>
              ) : (
                claims.map((claim) => (
                  <ClaimCard
                    key={claim.id}
                    claim={claim}
                    isExpanded={expandedIds.has(claim.id)}
                    onToggle={() => onToggle(claim.id)}
                  />
                ))
              )}
            </div>
          )
        })}
      </div>
    </>
  )
}

function AdminView({ pendingClaims, stagedClaims, sentClaims, onStage, onUnstage, onUpdatePending, onSendAll, onResend }) {
  return (
    <div className="admin-layout">
      {/* Top row: 2 columns side by side */}
      <div className="admin-top-row">
        {/* Left: Pending Claims List */}
        <div className="admin-panel admin-pending">
          <div className="admin-panel-header">
            <h2>Pending Claims</h2>
            <span className="panel-count">{pendingClaims.length}</span>
          </div>
          {pendingClaims.length === 0 ? (
            <div className="admin-panel-empty">
              <p>Keine Claims zur Bearbeitung</p>
              <p className="empty-subtitle">Warte auf neue Claims...</p>
            </div>
          ) : (
            <div className="admin-claims-list">
              {pendingClaims.map((claim) => (
                <div key={claim.id} className="admin-claim-item pending-item">
                  <div className="claim-content">
                    <input
                      type="text"
                      className="claim-speaker-edit"
                      value={claim.name}
                      onChange={(e) => onUpdatePending(claim.id, 'name', e.target.value)}
                      placeholder="Sprecher"
                    />
                    <textarea
                      className="claim-text-edit"
                      value={claim.claim}
                      onChange={(e) => onUpdatePending(claim.id, 'claim', e.target.value)}
                      placeholder="Claim"
                      rows={3}
                    />
                    <div className="claim-meta">
                      {new Date(claim.timestamp).toLocaleString('de-DE')}
                    </div>
                  </div>
                  <button
                    className="stage-button"
                    onClick={() => onStage(claim.id)}
                    title="Zum Staging hinzufügen"
                  >
                    →
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Right: Staging Area */}
        <div className="admin-panel admin-staging">
          <div className="admin-panel-header">
            <h2>Staging Area</h2>
            <span className="panel-count">{stagedClaims.length}</span>
          </div>
          {stagedClaims.length === 0 ? (
            <div className="admin-panel-empty">
              <p>Keine Claims bereit zum Senden</p>
              <p className="empty-subtitle">Klicke → bei einem Claim</p>
            </div>
          ) : (
            <>
              <div className="admin-claims-list">
                {stagedClaims.map((claim) => (
                  <div key={claim.id} className="admin-claim-item staged-item">
                    <button
                      className="unstage-button"
                      onClick={() => onUnstage(claim.id)}
                      title="Zurück zum Bearbeiten"
                    >
                      ←
                    </button>
                    <div className="claim-content readonly">
                      <div className="claim-speaker-display">{claim.name || 'Unbekannt'}</div>
                      <div className="claim-text-display">{claim.claim}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="staging-actions">
                <button
                  className="action-button primary send-all-button"
                  onClick={onSendAll}
                >
                  Alle {stagedClaims.length} Claims senden
                </button>
              </div>
            </>
          )}
        </div>
      </div>

      {/* Bottom row: Sent Claims History */}
      <div className="admin-bottom-row">
        <div className="admin-panel admin-sent">
          <div className="admin-panel-header">
            <h2>Gesendete Claims</h2>
            <span className="panel-count">{sentClaims.length}</span>
          </div>
          {sentClaims.length === 0 ? (
            <div className="admin-panel-empty compact">
              <p>Noch keine Claims gesendet</p>
            </div>
          ) : (
            <div className="sent-claims-list">
              {sentClaims.map((claim) => (
                <div key={claim.id} className="sent-claim-item">
                  <div className="sent-claim-content">
                    <span className="sent-speaker">{claim.name || 'Unbekannt'}</span>
                    <span className="sent-text">{claim.claim}</span>
                    <span className="sent-timestamp">
                      {new Date(claim.sentAt).toLocaleString('de-DE')}
                    </span>
                  </div>
                  <button
                    className="resend-button"
                    onClick={() => onResend(claim.id)}
                    title="Erneut senden (kopiert zu Pending)"
                  >
                    Re-send
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

function ClaimCard({ claim, isExpanded, onToggle }) {
  const getConsistencyColor = (consistency) => {
    const lower = consistency?.toLowerCase() || ''
    if (lower === 'hoch') return '#22c55e'
    if (lower === 'niedrig') return '#ef4444'
    if (lower === 'mittel') return '#f59e0b'
    return '#6b7280' // unklar or unknown
  }

  const getConsistencyClass = (consistency) => {
    const lower = consistency?.toLowerCase() || ''
    if (lower === 'hoch') return 'verdict-richtig'
    if (lower === 'niedrig') return 'verdict-falsch'
    if (lower === 'mittel') return 'verdict-teilweise'
    return 'verdict-unbelegt' // unklar or unknown
  }

  // Formatiert Begründung: Zeilenumbrüche und einfaches Markdown
  const formatBegruendung = (text) => {
    if (!text) return null

    // Ersetze \n\n durch Absätze
    const paragraphs = text.split(/\n\n+/).filter(p => p.trim())

    return paragraphs.map((para, idx) => {
      // Ersetze einzelne \n durch <br>
      const lines = para.split('\n')
      return (
        <p key={idx} className="begruendung-text">
          {lines.map((line, lineIdx) => (
            <React.Fragment key={lineIdx}>
              {lineIdx > 0 && <br />}
              {formatMarkdown(line)}
            </React.Fragment>
          ))}
        </p>
      )
    })
  }

  // Einfaches Markdown-Formatting (fett, kursiv, Links)
  const formatMarkdown = (text) => {
    if (!text) return text

    // Einfache Markdown-Patterns
    // **bold** -> <strong>
    // *italic* -> <em>
    // [text](url) -> <a>

    let match
    const matches = []

    // Reset lastIndex for global regex patterns (they maintain state)
    MARKDOWN_BOLD_PATTERN.lastIndex = 0
    MARKDOWN_ITALIC_PATTERN.lastIndex = 0
    MARKDOWN_LINK_PATTERN.lastIndex = 0

    // Pattern für **bold**
    while ((match = MARKDOWN_BOLD_PATTERN.exec(text)) !== null) {
      matches.push({
        type: 'bold',
        start: match.index,
        end: match.index + match[0].length,
        content: match[1]
      })
    }

    // Pattern für *italic*
    while ((match = MARKDOWN_ITALIC_PATTERN.exec(text)) !== null) {
      matches.push({
        type: 'italic',
        start: match.index,
        end: match.index + match[0].length,
        content: match[1]
      })
    }

    // Pattern für [text](url)
    while ((match = MARKDOWN_LINK_PATTERN.exec(text)) !== null) {
      matches.push({
        type: 'link',
        start: match.index,
        end: match.index + match[0].length,
        text: match[1],
        url: match[2]
      })
    }

    // Sortiere Matches nach Position
    matches.sort((a, b) => a.start - b.start)

    // Baue React-Elemente
    if (matches.length === 0) {
      return text
    }

    const elements = []
    let currentIndex = 0

    matches.forEach((match, idx) => {
      // Text vor dem Match
      if (match.start > currentIndex) {
        elements.push(text.substring(currentIndex, match.start))
      }

      // Das Match selbst
      if (match.type === 'bold') {
        elements.push(<strong key={`bold-${idx}`}>{match.content}</strong>)
      } else if (match.type === 'italic') {
        elements.push(<em key={`italic-${idx}`}>{match.content}</em>)
      } else if (match.type === 'link') {
        elements.push(
          <a key={`link-${idx}`} href={match.url} target="_blank" rel="noopener noreferrer" className="begruendung-link">
            {match.text}
          </a>
        )
      }

      currentIndex = match.end
    })

    // Rest des Textes
    if (currentIndex < text.length) {
      elements.push(text.substring(currentIndex))
    }

    return elements.length > 0 ? <>{elements}</> : text
  }

  const consistencyClass = getConsistencyClass(claim.consistency)

  return (
    <div className={`claim-card ${consistencyClass}`}>
      <div className="claim-header">
        <div className="claim-text">{claim.behauptung}</div>
        <button
          className="expand-button"
          onClick={onToggle}
          aria-label={isExpanded ? 'Einklappen' : 'Ausklappen'}
        >
          {isExpanded ? '▼' : '▶'}
        </button>
      </div>

      {isExpanded && (
        <div className="claim-details">
          <div className="detail-section">
            <h3>Datenbasierte Fundierung</h3>
            <div
              className="verdict-badge"
              style={{ backgroundColor: getConsistencyColor(claim.consistency) }}
            >
              {claim.consistency}
            </div>
          </div>

          <div className="detail-section">
            <h3>Begründung</h3>
            {claim.begruendung ? (
              <div className="begruendung-container">
                {formatBegruendung(claim.begruendung)}
              </div>
            ) : (
              <p className="begruendung-text no-begruendung">
                Keine Begründung verfügbar
              </p>
            )}
          </div>

          {claim.quellen && claim.quellen.length > 0 && (
            <div className="detail-section">
              <h3>Quellen</h3>
              <ul className="sources-list">
                {claim.quellen.map((quelle, idx) => (
                  <li key={idx}>
                    <a
                      href={quelle}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="source-link"
                    >
                      {quelle}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Footer() {
  return (
    <footer className="app-footer">
      <div className="footer-content">
        <p className="footer-disclaimer">
          Die hier dargestellten Fakten-Checks werden automatisch mit Hilfe von
          Künstlicher Intelligenz (KI) generiert. Die Inhalte können Fehler enthalten und sollten nicht
          als alleinige Grundlage für Entscheidungen verwendet werden. Wir übernehmen keine Gewähr für
          die Richtigkeit, Vollständigkeit oder Aktualität der Informationen.
        </p>
        <p className="footer-meta">
          Diese Seite dient ausschließlich zu Informationszwecken. Bei Fragen oder Anmerkungen kontaktieren
          Sie bitte den Betreiber dieser Seite.
        </p>
      </div>
    </footer>
  )
}

export default App
