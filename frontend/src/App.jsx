import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
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

// Backend URL - wird basierend auf Environment angepasst
const getBackendUrl = () => {
  // In Produktion: Backend URL über ngrok/Cloudflare Tunnel
  // Setze VITE_BACKEND_URL in .env oder als Environment Variable
  if (import.meta.env.PROD) {
    // Versuche Environment Variable, sonst Fallback auf localhost (für lokale Tests)
    return import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
  }
  // In Entwicklung: localhost
  return 'http://localhost:5000'
}

const BACKEND_URL = getBackendUrl()

function App() {
  const [shows, setShows] = useState(['test', 'maischberger', 'miosga'])  // Fallback
  
  // Lade Shows dynamisch vom Backend für Routes
  useEffect(() => {
    const loadShows = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows`)
        if (response.ok) {
          const data = await response.json()
          if (data.shows && data.shows.length > 0) {
            setShows(data.shows)
          }
        }
      } catch (error) {
        console.error('❌ Fehler beim Laden der Shows für Routes:', error)
      }
    }
    loadShows()
  }, [])
  
  return (
    <BrowserRouter basename={import.meta.env.PROD ? '/live_faktencheck' : ''}>
      <div className="app">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/test" element={<FactCheckPage showName="Test" showKey="test" episodeKey="test" />} />
          {/* Dynamische Routes für alle Shows */}
          {shows.filter(s => s !== 'test').map(show => (
            <Route 
              key={show} 
              path={`/${show}/:episode?`} 
              element={<ShowPage showKey={show} />} 
            />
          ))}
        </Routes>
      </div>
    </BrowserRouter>
  )
}

function Navigation() {
  const location = useLocation()
  const [shows, setShows] = useState(['test', 'maischberger', 'miosga'])  // Fallback
  
  // Lade Shows dynamisch vom Backend
  useEffect(() => {
    const loadShows = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows`)
        if (response.ok) {
          const data = await response.json()
          if (data.shows && data.shows.length > 0) {
            setShows(data.shows)
          }
        }
      } catch (error) {
        console.error('❌ Fehler beim Laden der Shows für Navigation:', error)
      }
    }
    loadShows()
  }, [])
  
  return (
    <nav className="main-navigation">
      <div className="nav-container">
        <Link to="/" className="nav-logo">🔍 Live Fakten-Check</Link>
        <div className="nav-links">
          {shows.map(show => (
            <Link 
              key={show} 
              to={`/${show}`} 
              className={location.pathname.startsWith(`/${show}`) ? 'active' : ''}
            >
              {show.charAt(0).toUpperCase() + show.slice(1)}
            </Link>
          ))}
        </div>
      </div>
    </nav>
  )
}

function HomePage() {
  const [shows, setShows] = useState([])
  
  useEffect(() => {
    const loadShows = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows`)
        if (response.ok) {
          const data = await response.json()
          setShows(data.shows || [])
        }
      } catch (error) {
        console.error('❌ Fehler beim Laden der Shows:', error)
      }
    }
    loadShows()
  }, [])
  
  return (
    <div className="home-page">
      <header className="app-header">
        <h1>🔍 Live Fakten-Check</h1>
        <p className="subtitle">Wähle eine Sendung aus</p>
      </header>
      <main className="main-content">
        <div className="show-selection">
          <Link to="/test" className="show-card">
            <h2>Test</h2>
            <p>Test-Umgebung für Fact-Checks</p>
          </Link>
          {shows.filter(s => s !== 'test').map(show => (
            <Link key={show} to={`/${show}`} className="show-card">
              <h2>{show.charAt(0).toUpperCase() + show.slice(1)}</h2>
              <p>Fact-Checks der {show.charAt(0).toUpperCase() + show.slice(1)} Sendung</p>
            </Link>
          ))}
        </div>
      </main>
    </div>
  )
}

function ShowPage({ showKey }) {
  const location = useLocation()
  const [episodes, setEpisodes] = useState([])
  const [selectedEpisode, setSelectedEpisode] = useState(null)
  const [showName, setShowName] = useState(showKey.charAt(0).toUpperCase() + showKey.slice(1))
  
  // Lade Episoden für diese Show
  useEffect(() => {
    const loadEpisodes = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/shows/${showKey}/episodes`)
        if (response.ok) {
          const data = await response.json()
          const episodesList = data.episodes || []
          setEpisodes(episodesList)
          
          // Setze erste Episode als Standard oder die aus der URL
          const episodeFromUrl = location.pathname.split('/').pop()
          if (episodeFromUrl && episodeFromUrl !== showKey) {
            const found = episodesList.find(e => e.key === episodeFromUrl)
            if (found) {
              setSelectedEpisode(found.key)
              setShowName(found.config.name || showName)
            } else if (episodesList.length > 0) {
              setSelectedEpisode(episodesList[0].key)
              setShowName(episodesList[0].config.name || showName)
            }
          } else if (episodesList.length > 0) {
            setSelectedEpisode(episodesList[0].key)
            setShowName(episodesList[0].config.name || showName)
            // Navigiere zur ersten Episode
            window.history.replaceState(null, '', `/${showKey}/${episodesList[0].key}`)
          }
        }
      } catch (error) {
        console.error('❌ Fehler beim Laden der Episoden:', error)
      }
    }
    loadEpisodes()
  }, [showKey, location.pathname])
  
  const handleEpisodeChange = (episodeKey) => {
    setSelectedEpisode(episodeKey)
    const episode = episodes.find(e => e.key === episodeKey)
    if (episode) {
      setShowName(episode.config.name || showName)
      window.history.replaceState(null, '', `/${showKey}/${episodeKey}`)
    }
  }
  
  if (!selectedEpisode) {
    return <div>Lade Episoden...</div>
  }
  
  return (
    <>
      <div style={{ padding: '1rem', background: '#f5f5f5', borderBottom: '1px solid #ddd' }}>
        <label style={{ display: 'block', marginBottom: '0.5rem', fontWeight: 'bold' }}>
          Episode auswählen:
        </label>
        <select
          value={selectedEpisode}
          onChange={(e) => handleEpisodeChange(e.target.value)}
          style={{
            padding: '0.5rem',
            fontSize: '1rem',
            borderRadius: '4px',
            border: '1px solid #ccc',
            minWidth: '300px'
          }}
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
  const isProduction = import.meta.env.PROD
  const isLocalhost = typeof window !== 'undefined' && 
    (window.location.hostname === 'localhost' || 
     window.location.hostname === '127.0.0.1' ||
     window.location.hostname.startsWith('192.168.'))
  const showAdminMode = !isProduction || isLocalhost
  
  const [isAdminMode, setIsAdminMode] = useState(false)
  const [factChecks, setFactChecks] = useState([])
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [pendingBlocks, setPendingBlocks] = useState([])
  const [selectedClaims, setSelectedClaims] = useState(new Set())
  const [editedClaims, setEditedClaims] = useState({})  // Speichert bearbeitete Claims: { "blockId-index": { name, claim } }
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Lädt Config vom Backend
  
  // Lade Episode-Konfiguration vom Backend
  useEffect(() => {
    const loadEpisodeConfig = async () => {
      // Verwende episodeKey (z.B. "maischberger-2025-09-19") oder showKey als Fallback
      const key = episodeKey || showKey || showName.toLowerCase()
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/${key}`)
        if (response.ok) {
          const config = await response.json()
          if (config.speakers && config.speakers.length > 0) {
            setSpeakers(config.speakers)
            console.log(`✅ Config geladen für ${key}:`, config)
          } else {
            console.warn(`⚠️ Keine Sprecher in Config für ${key}, verwende Fallback`)
          }
        } else {
          console.warn(`⚠️ Konnte Config nicht laden für ${key}, verwende Fallback`)
        }
      } catch (error) {
        console.error(`❌ Fehler beim Laden der Config für ${key}:`, error)
      }
    }
    
    loadEpisodeConfig()
  }, [showName, showKey, episodeKey])

  // Polling für Fact-Checks (nur im normalen Modus)
  useEffect(() => {
    if (isAdminMode) return

    const fetchFactChecks = async () => {
      try {
        // Lade immer vom Backend (auch in Produktion, wenn Backend über ngrok/Cloudflare Tunnel erreichbar ist)
        const url = episodeKey 
          ? `${BACKEND_URL}/api/fact-checks?episode=${episodeKey}`
          : `${BACKEND_URL}/api/fact-checks`
        
        const response = await fetch(url)
        if (!response.ok) {
          // Fallback: Versuche JSON-Datei zu laden (wenn Backend nicht erreichbar)
          if (import.meta.env.PROD && episodeKey) {
            try {
              const jsonResponse = await fetch(`/live_faktencheck/data/${episodeKey}.json`)
              if (jsonResponse.ok) {
                const data = await jsonResponse.json()
                console.log(`📊 Geladene Fakten-Checks (Fallback JSON): ${data.length}`, data)
                setFactChecks(data)
                return
              }
            } catch (e) {
              console.warn('⚠️ Auch JSON-Fallback fehlgeschlagen')
            }
          }
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        
        const data = await response.json()
        console.log(`📊 Geladene Fakten-Checks (Live): ${data.length}`, data)
        setFactChecks(data)
      } catch (error) {
        console.error('❌ Fehler beim Laden der Fakten-Checks:', error)
        // In Produktion: Versuche JSON-Fallback
        if (import.meta.env.PROD && episodeKey) {
          try {
            const jsonResponse = await fetch(`/live_faktencheck/data/${episodeKey}.json`)
            if (jsonResponse.ok) {
              const data = await jsonResponse.json()
              console.log(`📊 Geladene Fakten-Checks (Fallback JSON): ${data.length}`, data)
              setFactChecks(data)
            }
          } catch (e) {
            // Ignoriere Fallback-Fehler
          }
        }
      }
    }

    fetchFactChecks()
    // Polling in allen Umgebungen (auch Produktion für Live-Updates)
    const interval = setInterval(fetchFactChecks, 2000)
    return () => clearInterval(interval)
  }, [isAdminMode, episodeKey])

  // Polling für Pending Claims (nur im Admin-Modus und nur lokal)
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return

    const fetchPendingClaims = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/pending-claims`)
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        const data = await response.json()
        console.log(`📋 Geladene Pending Blocks: ${data.length}`, data)
        setPendingBlocks(data)
      } catch (error) {
        console.error('❌ Fehler beim Laden der Pending Claims:', error)
      }
    }

    fetchPendingClaims()
    const interval = setInterval(fetchPendingClaims, 2000)
    return () => clearInterval(interval)
  }, [isAdminMode, isProduction])

  const toggleExpand = (id) => {
    const newExpanded = new Set(expandedIds)
    if (newExpanded.has(id)) {
      newExpanded.delete(id)
    } else {
      newExpanded.add(id)
    }
    setExpandedIds(newExpanded)
  }

  const toggleClaimSelection = (blockId, claimIndex) => {
    const key = `${blockId}-${claimIndex}`
    const newSelected = new Set(selectedClaims)
    if (newSelected.has(key)) {
      newSelected.delete(key)
    } else {
      newSelected.add(key)
    }
    setSelectedClaims(newSelected)
  }

  const selectAllClaims = (blockId, claims) => {
    const newSelected = new Set(selectedClaims)
    claims.forEach((_, index) => {
      newSelected.add(`${blockId}-${index}`)
    })
    setSelectedClaims(newSelected)
  }

  const deselectAllClaims = (blockId) => {
    const newSelected = new Set(selectedClaims)
    Array.from(newSelected).forEach(key => {
      if (key.startsWith(`${blockId}-`)) {
        newSelected.delete(key)
      }
    })
    setSelectedClaims(newSelected)
  }

  const updateEditedClaim = (blockId, claimIndex, field, value) => {
    const key = `${blockId}-${claimIndex}`
    setEditedClaims(prev => ({
      ...prev,
      [key]: {
        ...prev[key],
        [field]: value
      }
    }))
  }

  const sendApprovedClaims = async (blockId) => {
    const block = pendingBlocks.find(b => b.block_id === blockId)
    if (!block) return

    const approved = block.claims
      .map((claim, index) => {
        const key = `${blockId}-${index}`
        const edited = editedClaims[key]
        // Verwende bearbeitete Werte falls vorhanden, sonst Original
        return {
          name: edited?.name !== undefined ? edited.name : (claim.name || ''),
          claim: edited?.claim !== undefined ? edited.claim : (claim.claim || ''),
          _index: index
        }
      })
      .filter((_, index) => selectedClaims.has(`${blockId}-${index}`))

    if (approved.length === 0) {
      alert('Bitte wähle mindestens einen Claim aus!')
      return
    }

    try {
      const response = await fetch(`${BACKEND_URL}/api/approve-claims`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          block_id: blockId,
          claims: approved,
          n8n_webhook_url: N8N_VERIFIED_WEBHOOK
        })
      })

      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }

      const result = await response.json()
      console.log('✅ Claims gesendet:', result)
      alert(`✅ ${approved.length} Claims erfolgreich an N8N gesendet!`)
      
      // Entferne ausgewählte Claims und Bearbeitungen
      const newSelected = new Set(selectedClaims)
      const newEdited = { ...editedClaims }
      approved.forEach((_, index) => {
        const key = `${blockId}-${index}`
        newSelected.delete(key)
        delete newEdited[key]
      })
      setSelectedClaims(newSelected)
      setEditedClaims(newEdited)
    } catch (error) {
      console.error('❌ Fehler beim Senden:', error)
      alert(`❌ Fehler beim Senden: ${error.message}`)
    }
  }

  // Gruppiere Fakten-Checks nach Sprecher
  const groupedBySpeaker = speakers.reduce((acc, speaker) => {
    acc[speaker] = factChecks.filter(fc => fc.sprecher === speaker)
    return acc
  }, {})

  return (
    <>
      <header className="app-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', width: '100%' }}>
          <div>
            <h1>🔍 Fakten-Check - {showName}</h1>
            <p className="subtitle">{isAdminMode ? 'Admin-Modus: Claim-Überprüfung' : 'Live Fact-Checking Dashboard'}</p>
          </div>
          {showAdminMode && (
            <button
              className="admin-toggle"
              onClick={() => {
                setIsAdminMode(!isAdminMode)
                setSelectedClaims(new Set())
              }}
            >
              {isAdminMode ? '👤 Normal-Modus' : '⚙️ Admin-Modus'}
            </button>
          )}
        </div>
      </header>

      <main className="main-content">
        {isAdminMode ? (
          <AdminView
            pendingBlocks={pendingBlocks}
            selectedClaims={selectedClaims}
            editedClaims={editedClaims}
            onToggleClaim={toggleClaimSelection}
            onUpdateClaim={updateEditedClaim}
            onSelectAll={selectAllClaims}
            onDeselectAll={deselectAllClaims}
            onSendApproved={sendApprovedClaims}
          />
        ) : (
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
                          onToggle={() => toggleExpand(claim.id)}
                        />
                      ))
                    )}
                  </div>
                )
              })}
            </div>
          </>
        )}
      </main>
    </>
  )
}

function AdminView({ pendingBlocks, selectedClaims, editedClaims, onToggleClaim, onUpdateClaim, onSelectAll, onDeselectAll, onSendApproved }) {
  if (pendingBlocks.length === 0) {
    return (
      <div className="admin-empty">
        <p>⏳ Keine Claims zur Überprüfung vorhanden</p>
        <p style={{ fontSize: '0.9rem', color: '#666', marginTop: '1rem' }}>
          Warte auf neue Claims von N8N...
        </p>
      </div>
    )
  }

  return (
    <div className="admin-container">
      {pendingBlocks.map((block) => {
        const blockSelectedCount = block.claims.filter((_, index) => 
          selectedClaims.has(`${block.block_id}-${index}`)
        ).length
        const isAllSelected = block.claims.length > 0 && blockSelectedCount === block.claims.length

        return (
          <div key={block.block_id} className="admin-block">
            <div className="admin-block-header">
              <div>
                <h2>Block: {block.block_id}</h2>
                <p className="block-meta">
                  {new Date(block.timestamp).toLocaleString('de-DE')} • {block.claims_count} Claims
                </p>
              </div>
              <div className="block-actions">
                <button
                  className="action-button"
                  onClick={() => isAllSelected ? onDeselectAll(block.block_id) : onSelectAll(block.block_id, block.claims)}
                >
                  {isAllSelected ? '☐ Alle abwählen' : '☑ Alle auswählen'}
                </button>
                <button
                  className="action-button primary"
                  onClick={() => onSendApproved(block.block_id)}
                  disabled={blockSelectedCount === 0}
                >
                  📤 {blockSelectedCount} Claim{blockSelectedCount !== 1 ? 's' : ''} senden
                </button>
              </div>
            </div>

            <div className="admin-claims-list">
              {block.claims.map((claim, index) => {
                const claimKey = `${block.block_id}-${index}`
                const isSelected = selectedClaims.has(claimKey)
                const edited = editedClaims[claimKey] || {}
                const displayName = edited.name !== undefined ? edited.name : (claim.name || 'Unbekannt')
                const displayClaim = edited.claim !== undefined ? edited.claim : (claim.claim || '')

                return (
                  <div key={index} className={`admin-claim-item ${isSelected ? 'selected' : ''}`}>
                    <label className="claim-checkbox">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleClaim(block.block_id, index)}
                      />
                      <div className="claim-content">
                        <input
                          type="text"
                          className="claim-speaker-edit"
                          value={displayName}
                          onChange={(e) => onUpdateClaim(block.block_id, index, 'name', e.target.value)}
                          placeholder="Sprecher"
                          onClick={(e) => e.stopPropagation()}
                        />
                        <textarea
                          className="claim-text-edit"
                          value={displayClaim}
                          onChange={(e) => onUpdateClaim(block.block_id, index, 'claim', e.target.value)}
                          placeholder="Claim"
                          rows={3}
                          onClick={(e) => e.stopPropagation()}
                        />
                      </div>
                    </label>
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function ClaimCard({ claim, isExpanded, onToggle }) {
  const getVerdictColor = (urteil) => {
    const lower = urteil?.toLowerCase() || ''
    if (lower.includes('wahr') || lower.includes('richtig')) return '#22c55e'
    if (lower.includes('falsch') || lower.includes('unwahr')) return '#ef4444'
    if (lower.includes('teilweise')) return '#f59e0b'
    return '#6b7280'
  }

  return (
    <div className="claim-card">
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
            <h3>Urteil</h3>
            <div
              className="verdict-badge"
              style={{ backgroundColor: getVerdictColor(claim.urteil) }}
            >
              {claim.urteil}
            </div>
          </div>

          <div className="detail-section">
            <h3>Begründung</h3>
            {claim.begruendung ? (
              <p className="begruendung-text">{claim.begruendung}</p>
            ) : (
              <p className="begruendung-text" style={{ color: '#999', fontStyle: 'italic' }}>
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

export default App
