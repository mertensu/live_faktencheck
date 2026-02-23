import { useState, useEffect, useRef } from 'react'
import { BACKEND_URL, N8N_VERIFIED_WEBHOOK, getFetchHeaders, safeJsonParse, debug } from '../services/api'
import { AdminView } from '../components/AdminView'
import { SpeakerColumns } from '../components/SpeakerColumns'
import { BackendErrorDisplay } from '../components/BackendErrorDisplay'

// Default speakers as fallback
const DEFAULT_SPEAKERS = [
  'Sandra Maischberger',
  'Gitta Connemann',
  'Katharina Droge'
]

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

export function FactCheckPage({ showName, showKey, episodeKey }) {
  // Admin mode available when:
  // 1. Not in production (development) OR
  // 2. Local on localhost (even with production build)
  // 3. If ?admin=true in URL
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
  // Admin workflow: flat list -> staging -> sent history
  const [pendingClaims, setPendingClaims] = useState([])   // Flat list of editable claims
  const [pendingBlocks, setPendingBlocks] = useState([])   // Claims grouped by source block
  const [stagedClaims, setStagedClaims] = useState([])     // Ready to send (read-only)
  const [discardedClaims, setDiscardedClaims] = useState([]) // Discarded/irrelevant claims
  const [sentClaims, setSentClaims] = useState([])         // History with timestamps
  const [localEdits, setLocalEdits] = useState({})         // Track local edits: { claimId: { name, claim } }
  const localEditsRef = useRef(localEdits)                   // Ref to access current edits in polling
  localEditsRef.current = localEdits                         // Keep ref in sync with state
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Load config from backend
  const [backendError, setBackendError] = useState(null)  // Backend connection error

  // Static mode: production build on non-localhost → load from /data/<episode>.json once
  const isStaticMode = isProduction && !isLocalhost

  // Load episode configuration from backend (skipped in static mode — config comes from JSON)
  useEffect(() => {
    if (isStaticMode) return
    const controller = new AbortController()

    const loadEpisodeConfig = async () => {
      const key = episodeKey || showKey || showName.toLowerCase()
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/${key}`, {
          headers: getFetchHeaders(),
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

  useEffect(() => {
    if (!isStaticMode || isAdminMode) return
    const key = episodeKey || showKey || showName?.toLowerCase()
    if (!key) return

    fetch(`/data/${key}.json`)
      .then(r => {
        if (!r.ok) throw new Error(`No static data for ${key}`)
        return r.json()
      })
      .then(data => {
        setFactChecks(data.fact_checks || [])
        if (data.speakers?.length > 0) setSpeakers(data.speakers)
      })
      .catch(() => {}) // silently fail — no static file yet
  }, [isStaticMode, isAdminMode, episodeKey, showKey, showName])

  // Polling for fact-checks (only in normal mode, only when backend is available)
  useEffect(() => {
    if (isAdminMode) return
    if (isStaticMode) return

    let isMounted = true
    let currentController = null

    const fetchFactChecks = async () => {
      const controller = new AbortController()
      currentController = controller

      try {
        const url = episodeKey
          ? `${BACKEND_URL}/api/fact-checks?episode=${episodeKey}`
          : `${BACKEND_URL}/api/fact-checks`

        debug.log(`Loading fact-checks from: ${url}`)

        // Timeout: abort after 5 seconds
        const timeoutId = setTimeout(() => controller.abort(), 5000)

        const response = await fetch(url, {
          headers: getFetchHeaders(),
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
        setFactChecks(data)
        setBackendError(null)  // Clear error on success
      } catch (error) {
        if (!isMounted) return

        if (error.name === 'AbortError') {
          setBackendError({
            message: 'Backend request timed out',
            backendUrl: BACKEND_URL,
            episodeKey: episodeKey
          })
        } else {
          debug.error('Error loading from backend:', error)
          setBackendError({
            message: error.message || 'Unknown error',
            backendUrl: BACKEND_URL,
            episodeKey: episodeKey
          })
        }
        setFactChecks([])  // Clear fact checks on error
      }
    }

    fetchFactChecks()
    const interval = setInterval(fetchFactChecks, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [isAdminMode, episodeKey])

  // Polling for pending claims (only in admin mode and only local)
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return

    let isMounted = true
    let currentController = null

    const fetchPendingClaimsFromBackend = async () => {
      const controller = new AbortController()
      currentController = controller

      try {
        const pendingUrl = episodeKey
          ? `${BACKEND_URL}/api/pending-claims?episode=${episodeKey}`
          : `${BACKEND_URL}/api/pending-claims`
        const response = await fetch(pendingUrl, {
          headers: getFetchHeaders(),
          signal: controller.signal
        })

        if (!isMounted) return

        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`)
        }
        const data = await safeJsonParse(response, 'Error loading pending claims')
        debug.log(`Loaded pending blocks: ${data.length}`, data)

        // Flatten blocks into claims, excluding those already staged or sent
        const flatClaims = flattenPendingBlocks(data)
        const stagedIds = new Set(stagedClaims.map(c => c.id))
        const sentIds = new Set(sentClaims.map(c => c.originalId || c.id))
        const discardedIds = new Set(discardedClaims.map(c => c.id))
        const newPending = flatClaims.filter(c => !stagedIds.has(c.id) && !sentIds.has(c.id) && !discardedIds.has(c.id))
        const currentEdits = localEditsRef.current
        setPendingClaims(prev => {
          // Preserve locally-added resend claims (not from backend)
          const localResendClaims = prev.filter(c => c.resendOf)
          const merged = [
            ...localResendClaims,
            ...newPending.map(claim =>
              currentEdits[claim.id] ? { ...claim, ...currentEdits[claim.id] } : claim
            )
          ]
          return merged
        })

        // Build pendingBlocks: group enriched claims by block, newest first
        const filteredIds = new Set([...stagedIds, ...sentIds, ...discardedIds])
        const blocks = data
          .map(block => {
            const enrichedClaims = block.claims
              .map((claim, index) => {
                const id = `${block.block_id}-${index}`
                const base = {
                  id,
                  blockId: block.block_id,
                  name: claim.name || '',
                  claim: claim.claim || '',
                  timestamp: block.timestamp,
                  info: block.info || block.headline || ''
                }
                return filteredIds.has(id) ? null : (currentEdits[id] ? { ...base, ...currentEdits[id] } : base)
              })
              .filter(Boolean)
            return enrichedClaims.length > 0
              ? { blockId: block.block_id, timestamp: block.timestamp, info: block.info || block.headline || '', claims: enrichedClaims }
              : null
          })
          .filter(Boolean)
          .sort((a, b) => new Date(b.timestamp) - new Date(a.timestamp))
        setPendingBlocks(blocks)
      } catch (error) {
        if (!isMounted || error.name === 'AbortError') return
        debug.error('Error loading pending claims:', error)
      }
    }

    fetchPendingClaimsFromBackend()
    const interval = setInterval(fetchPendingClaimsFromBackend, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [isAdminMode, showAdminMode, stagedClaims, sentClaims, discardedClaims])

  const toggleExpand = (id) => {
    const newExpanded = new Set(expandedIds)
    if (newExpanded.has(id)) {
      newExpanded.delete(id)
    } else {
      newExpanded.add(id)
    }
    setExpandedIds(newExpanded)
  }

  // Move claim from pending -> staging (with current edits)
  const stageClaimForSending = (claimId) => {
    const claim = pendingClaims.find(c => c.id === claimId)
    if (!claim) return
    setStagedClaims(prev => [...prev, { ...claim }])
    setPendingClaims(prev => prev.filter(c => c.id !== claimId))
    // Clear local edits for this claim
    setLocalEdits(prev => {
      const { [claimId]: _, ...rest } = prev
      return rest
    })
  }

  // Move claim from staging -> pending (for further editing)
  const unstageClaim = (claimId) => {
    const claim = stagedClaims.find(c => c.id === claimId)
    if (!claim) return
    setPendingClaims(prev => [...prev, { ...claim }].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)))
    setStagedClaims(prev => prev.filter(c => c.id !== claimId))
  }

  // Move claim from pending -> discarded
  const discardClaim = (claimId) => {
    const claim = pendingClaims.find(c => c.id === claimId)
    if (!claim) return
    setDiscardedClaims(prev => [...prev, { ...claim }])
    setPendingClaims(prev => prev.filter(c => c.id !== claimId))
    setLocalEdits(prev => {
      const { [claimId]: _, ...rest } = prev
      return rest
    })
  }

  // Move claim from discarded -> pending
  const undiscardClaim = (claimId) => {
    const claim = discardedClaims.find(c => c.id === claimId)
    if (!claim) return
    setPendingClaims(prev => [...prev, { ...claim }].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)))
    setDiscardedClaims(prev => prev.filter(c => c.id !== claimId))
  }

  // Discard all claims in a collection (block)
  const discardCollection = (blockId) => {
    const claimsToDiscard = pendingClaims.filter(c => c.blockId === blockId && !c.resendOf)
    setDiscardedClaims(prev => [...prev, ...claimsToDiscard])
    setPendingClaims(prev => prev.filter(c => c.blockId !== blockId || c.resendOf))
    setLocalEdits(prev => {
      const next = { ...prev }
      claimsToDiscard.forEach(c => delete next[c.id])
      return next
    })
  }

  // Edit claim in pending list
  const updatePendingClaim = (claimId, field, value) => {
    setPendingClaims(prev => prev.map(c =>
      c.id === claimId ? { ...c, [field]: value } : c
    ))
    setPendingBlocks(prev => prev.map(block => ({
      ...block,
      claims: block.claims.map(c =>
        c.id === claimId ? { ...c, [field]: value } : c
      )
    })))
    setLocalEdits(prev => ({
      ...prev,
      [claimId]: { ...(prev[claimId] || {}), [field]: value }
    }))
  }

  // Send all staged claims to backend for fact-checking
  const sendStagedClaims = async () => {
    if (stagedClaims.length === 0) {
      alert('Keine Claims zum Senden ausgewahlt!')
      return
    }

    // Separate new claims from re-sends (use resendOf flag, not factCheckId)
    const newClaims = stagedClaims.filter(c => !c.resendOf)
    const resendClaims = stagedClaims.filter(c => c.resendOf)

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

        const result = await safeJsonParse(response, 'Error sending new claims')
        debug.log('New claims sent:', result)
        results.push(`${newClaims.length} neue Claims`)
      }

      // Send re-sends via POST to /resend endpoint (matches by speaker+claim text)
      for (const claim of resendClaims) {
        const response = await fetch(`${BACKEND_URL}/api/fact-checks/resend`, {
          method: 'POST',
          headers: getFetchHeaders(),
          body: JSON.stringify({
            name: claim.name,
            claim: claim.claim,
            fact_check_id: claim.originalFactCheckId || null,
            original_claim: claim.originalClaim || null
          })
        })

        if (!response.ok) {
          debug.warn(`Error re-sending claim:`, response.status)
        } else {
          debug.log(`Re-send for "${claim.name}" started`)
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

      alert(`Erfolgreich gesendet: ${results.join(', ')}`)
    } catch (error) {
      debug.error('Error sending:', error)
      alert(`Fehler beim Senden: ${error.message}`)
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
      originalFactCheckId: claim.factCheckId,
      originalClaim: claim.claim
    }
    setPendingClaims(prev => [resendClaim, ...prev])
  }

  // Group fact-checks by speaker
  // Supports exact match and partial match (e.g., "Connemann" matches "Gitta Connemann")
  const groupedBySpeaker = speakers.reduce((acc, speaker) => {
    acc[speaker] = factChecks.filter(fc => {
      const factCheckSpeaker = fc.sprecher || ''
      // Exact match
      if (factCheckSpeaker === speaker) return true
      // Partial match: if config speaker contains fact-check speaker or vice versa
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
          </div>
          {showAdminMode && (
            <button
              className="admin-toggle"
              onClick={() => setIsAdminMode(!isAdminMode)}
            >
              {isAdminMode ? 'Normal-Modus' : 'Admin-Modus'}
            </button>
          )}
        </div>
      </header>

      <main className="main-content">
        {isAdminMode ? (
          <AdminView
            pendingClaims={pendingClaims}
            pendingBlocks={pendingBlocks}
            stagedClaims={stagedClaims}
            discardedClaims={discardedClaims}
            sentClaims={sentClaims}
            onStage={stageClaimForSending}
            onUnstage={unstageClaim}
            onDiscard={discardClaim}
            onUndiscard={undiscardClaim}
            onDiscardCollection={discardCollection}
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
