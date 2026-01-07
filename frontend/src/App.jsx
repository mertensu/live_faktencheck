import React, { useState, useEffect } from 'react'
import { BrowserRouter, Routes, Route, Link, useLocation } from 'react-router-dom'
import './App.css'

// Konfiguration: Hier können die Sprecher angepasst werden
const SPEAKERS = [
  'Sandra Maischberger',
  'Gitta Connemann',
  'Katharina Dröge'
]

// N8N Webhook URL für verified claims
const N8N_VERIFIED_WEBHOOK = "http://localhost:5678/webhook/verified-claims"

// Backend URL - wird basierend auf Environment angepasst
const getBackendUrl = () => {
  // In Produktion: Backend URL (wird später konfiguriert)
  if (import.meta.env.PROD) {
    return import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'
  }
  // In Entwicklung: localhost
  return 'http://localhost:5000'
}

const BACKEND_URL = getBackendUrl()

function App() {
  return (
    <BrowserRouter basename={import.meta.env.PROD ? '/live_faktencheck' : ''}>
      <div className="app">
        <Navigation />
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/test" element={<FactCheckPage showName="Test" />} />
          <Route path="/maischberger" element={<FactCheckPage showName="Maischberger" />} />
        </Routes>
      </div>
    </BrowserRouter>
  )
}

function Navigation() {
  const location = useLocation()
  
  return (
    <nav className="main-navigation">
      <div className="nav-container">
        <Link to="/" className="nav-logo">🔍 Live Fakten-Check</Link>
        <div className="nav-links">
          <Link to="/test" className={location.pathname === '/test' ? 'active' : ''}>
            Test
          </Link>
          <Link to="/maischberger" className={location.pathname === '/maischberger' ? 'active' : ''}>
            Maischberger
          </Link>
        </div>
      </div>
    </nav>
  )
}

function HomePage() {
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
          <Link to="/maischberger" className="show-card">
            <h2>Maischberger</h2>
            <p>Fact-Checks der Maischberger Sendung</p>
          </Link>
        </div>
      </main>
    </div>
  )
}

function FactCheckPage({ showName }) {
  const isProduction = import.meta.env.PROD
  const [isAdminMode, setIsAdminMode] = useState(false)
  const [factChecks, setFactChecks] = useState([])
  const [expandedIds, setExpandedIds] = useState(new Set())
  const [pendingBlocks, setPendingBlocks] = useState([])
  const [selectedClaims, setSelectedClaims] = useState(new Set())

  // Polling für Fact-Checks (nur im normalen Modus)
  useEffect(() => {
    if (isAdminMode) return

    const fetchFactChecks = async () => {
      try {
        const response = await fetch(`${BACKEND_URL}/api/fact-checks`)
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        const data = await response.json()
        console.log(`📊 Geladene Fakten-Checks: ${data.length}`, data)
        setFactChecks(data)
      } catch (error) {
        console.error('❌ Fehler beim Laden der Fakten-Checks:', error)
      }
    }

    fetchFactChecks()
    const interval = setInterval(fetchFactChecks, 2000)
    return () => clearInterval(interval)
  }, [isAdminMode])

  // Polling für Pending Claims (nur im Admin-Modus und nur lokal)
  useEffect(() => {
    if (!isAdminMode || isProduction) return

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

  const sendApprovedClaims = async (blockId) => {
    const block = pendingBlocks.find(b => b.block_id === blockId)
    if (!block) return

    const approved = block.claims
      .map((claim, index) => ({ ...claim, _index: index }))
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
      
      // Entferne ausgewählte Claims
      const newSelected = new Set(selectedClaims)
      approved.forEach((_, index) => {
        newSelected.delete(`${blockId}-${index}`)
      })
      setSelectedClaims(newSelected)
    } catch (error) {
      console.error('❌ Fehler beim Senden:', error)
      alert(`❌ Fehler beim Senden: ${error.message}`)
    }
  }

  // Gruppiere Fakten-Checks nach Sprecher
  const groupedBySpeaker = SPEAKERS.reduce((acc, speaker) => {
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
          {!isProduction && (
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
            onToggleClaim={toggleClaimSelection}
            onSelectAll={selectAllClaims}
            onDeselectAll={deselectAllClaims}
            onSendApproved={sendApprovedClaims}
          />
        ) : (
          <>
            {/* Sprecher Header - nebeneinander */}
            <div className="speakers-container">
              {SPEAKERS.map((speaker) => {
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
              {SPEAKERS.map((speaker) => {
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

function AdminView({ pendingBlocks, selectedClaims, onToggleClaim, onSelectAll, onDeselectAll, onSendApproved }) {
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

                return (
                  <div key={index} className={`admin-claim-item ${isSelected ? 'selected' : ''}`}>
                    <label className="claim-checkbox">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleClaim(block.block_id, index)}
                      />
                      <div className="claim-content">
                        <div className="claim-speaker">{claim.name || 'Unbekannt'}</div>
                        <div className="claim-text">{claim.claim}</div>
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
