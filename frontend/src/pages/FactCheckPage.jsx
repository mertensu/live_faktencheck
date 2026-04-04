import { useState, useEffect, useRef, useMemo } from 'react'
import { BACKEND_URL, N8N_VERIFIED_WEBHOOK, FETCH_HEADERS, safeJsonParse, debug } from '../services/api'
import { AdminView } from '../components/AdminView'
import { SpeakerColumns } from '../components/SpeakerColumns'
import { BackendErrorDisplay } from '../components/BackendErrorDisplay'
import { ClaimDetailOverlay } from '../components/ClaimDetailOverlay'

// Default speakers as fallback
const DEFAULT_SPEAKERS = []

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
  const [selectedClaim, setSelectedClaim] = useState(null)
  const [pipelineEvents, setPipelineEvents] = useState([])  // Pipeline status events
  // Admin workflow: flat list -> staging -> sent history
  const [pendingClaims, setPendingClaims] = useState([])   // Flat list of editable claims
  const [pendingBlocks, setPendingBlocks] = useState([])   // Claims grouped by source block
  const [stagedClaims, setStagedClaims] = useState([])     // Ready to send (read-only)
  const [discardedClaims, setDiscardedClaims] = useState([]) // Discarded/irrelevant claims
  const [sentClaims, setSentClaims] = useState([])         // History with timestamps
  const [localEdits, setLocalEdits] = useState({})         // Track local edits: { claimId: { name, claim } }
  const localEditsRef = useRef(localEdits)                   // Ref to access current edits in polling
  localEditsRef.current = localEdits                         // Keep ref in sync with state
  const stagedClaimsRef = useRef(stagedClaims)
  stagedClaimsRef.current = stagedClaims
  const sentClaimsRef = useRef(sentClaims)
  sentClaimsRef.current = sentClaims
  const discardedClaimsRef = useRef(discardedClaims)
  discardedClaimsRef.current = discardedClaims
  const [speakers, setSpeakers] = useState(DEFAULT_SPEAKERS)  // Load config from backend
  const [displayTitle, setDisplayTitle] = useState(showName)  // Full show title (updated from config)
  const [backendError, setBackendError] = useState(null)  // Backend connection error

  // Static mode: production build on non-localhost → try /data/<episode>.json first,
  // fall back to live polling if no static file exists (live session in progress)
  const [isStaticMode, setIsStaticMode] = useState(isProduction && !isLocalhost)

  // Load episode configuration from backend (skipped in static mode — config comes from JSON)
  useEffect(() => {
    if (isStaticMode) return
    const controller = new AbortController()

    const loadEpisodeConfig = async () => {
      const key = episodeKey || showKey || showName.toLowerCase()
      try {
        const response = await fetch(`${BACKEND_URL}/api/config/${key}`, {
          headers: FETCH_HEADERS,
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
  }, [showName, showKey, episodeKey, isStaticMode])

  useEffect(() => {
    if (!isStaticMode || isAdminMode) return
    const key = episodeKey || showKey || showName?.toLowerCase()
    if (!key) return

    fetch(`/data/${key}.json`)
      .then(r => {
        if (!r.ok) throw new Error(`No static data for ${key}`)
        return r.json()
      })
      .then(async (data) => {
        // Check if backend is live for this episode — if so, use live polling instead
        try {
          const healthRes = await fetch(`${BACKEND_URL}/api/health`)
          if (healthRes.ok) {
            const health = await healthRes.json()
            if (health.current_episode === key) {
              setIsStaticMode(false)
              return
            }
          }
        } catch {
          // Backend not reachable — stay in static mode
        }
        setFactChecks(data.fact_checks || [])
        if (data.speakers?.length > 0) setSpeakers(data.speakers)
        if (data.show_name && data.date) {
          setDisplayTitle(`${data.show_name} vom ${data.date}`)
        } else if (data.show_name) {
          setDisplayTitle(data.show_name)
        }
      })
      .catch(() => setIsStaticMode(false)) // no static file → fall back to live polling
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
          headers: FETCH_HEADERS,
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
  }, [isAdminMode, isStaticMode, episodeKey])

  // Seed sentClaims from DB when entering admin mode (enables resend for past fact-checks)
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return
    const url = episodeKey
      ? `${BACKEND_URL}/api/fact-checks?episode=${episodeKey}`
      : `${BACKEND_URL}/api/fact-checks`
    fetch(url, { headers: FETCH_HEADERS })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setSentClaims(prev => {
          // Merge DB entries with existing sent claims (preserve in-session claims)
          const existingIds = new Set(prev.map(c => c.id))
          const dbEntries = data
            .map(fc => ({
              id: `db_${fc.id}`,
              originalId: `db_${fc.id}`,
              name: fc.sprecher,
              claim: fc.behauptung,
              sentAt: fc.timestamp,
              factCheckId: fc.id,
              originalClaim: fc.behauptung,
              blockId: null,
              info: null
            }))
            .filter(entry => !existingIds.has(entry.id))
          return [...prev, ...dbEntries]
        })
      })
      .catch(err => debug.warn('Could not seed sent claims from DB:', err))
  }, [isAdminMode, showAdminMode, episodeKey])

  // Seed discardedClaims from DB when entering admin mode
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return
    const url = episodeKey
      ? `${BACKEND_URL}/api/fact-checks?episode=${episodeKey}&status=discarded`
      : `${BACKEND_URL}/api/fact-checks?status=discarded`
    fetch(url, { headers: FETCH_HEADERS })
      .then(r => r.ok ? r.json() : Promise.reject(r.status))
      .then(data => {
        setDiscardedClaims(prev => {
          const existingIds = new Set(prev.map(c => c.id))
          const dbEntries = data
            .map(fc => ({
              id: `discarded_${fc.id}`,
              name: fc.sprecher,
              claim: fc.behauptung,
              blockId: null,
            }))
            .filter(entry => !existingIds.has(entry.id))
          return [...prev, ...dbEntries]
        })
      })
      .catch(err => debug.warn('Could not seed discarded claims from DB:', err))
  }, [isAdminMode, showAdminMode, episodeKey])

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
          headers: FETCH_HEADERS,
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
        const stagedIds = new Set(stagedClaimsRef.current.map(c => c.id))
        const sentIds = new Set(sentClaimsRef.current.map(c => c.originalId || c.id))
        const discardedIds = new Set(discardedClaimsRef.current.map(c => c.id))
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
  }, [isAdminMode, showAdminMode])

  // Polling for pipeline status (only in admin mode)
  useEffect(() => {
    if (!isAdminMode || !showAdminMode) return

    let isMounted = true
    let currentController = null

    const fetchPipelineStatus = async () => {
      const controller = new AbortController()
      currentController = controller
      try {
        const response = await fetch(`${BACKEND_URL}/api/pipeline-status`, {
          headers: FETCH_HEADERS,
          signal: controller.signal
        })
        if (!isMounted || !response.ok) return
        const data = await safeJsonParse(response, 'Error loading pipeline status')
        if (isMounted) setPipelineEvents(data)
      } catch (error) {
        if (isMounted && error.name !== 'AbortError') {
          debug.error('Error loading pipeline status:', error)
        }
      }
    }

    fetchPipelineStatus()
    const interval = setInterval(fetchPipelineStatus, 2000)

    return () => {
      isMounted = false
      if (currentController) currentController.abort()
      clearInterval(interval)
    }
  }, [isAdminMode, showAdminMode])

  const retriggerBlock = async (blockId) => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/pipeline-status/${blockId}/retrigger`, {
        method: 'POST',
        headers: FETCH_HEADERS
      })
      if (!response.ok) {
        const err = await response.json().catch(() => ({}))
        alert(`Fehler: ${err.detail || response.status}`)
      }
    } catch (error) {
      debug.error('Error retriggering block:', error)
      alert(`Fehler beim Neustarten: ${error.message}`)
    }
  }

  // Move claim from pending -> staging (with current edits)
  const stageClaimForSending = (claimId) => {
    const claim = pendingClaims.find(c => c.id === claimId)
    if (!claim) return
    setStagedClaims(prev => [...prev, { ...claim }])
    setPendingClaims(prev => prev.filter(c => c.id !== claimId))
    // Optimistically update pendingBlocks; dismiss from backend if block is now empty
    const sourceBlock = pendingBlocks.find(b => b.claims.some(c => c.id === claimId))
    if (sourceBlock && sourceBlock.claims.length === 1) dismissBlock(sourceBlock.blockId)
    setPendingBlocks(prev => prev
      .map(block => ({ ...block, claims: block.claims.filter(c => c.id !== claimId) }))
      .filter(block => block.claims.length > 0)
    )
    // Clear local edits for this claim
    setLocalEdits(prev => {
      const { [claimId]: _, ...rest } = prev
      return rest
    })
  }

  // Dismiss a pending block from the backend (best-effort cleanup)
  const dismissBlock = (blockId) => {
    if (!blockId) return
    fetch(`${BACKEND_URL}/api/pending-claims/${blockId}`, {
      method: 'DELETE',
      headers: FETCH_HEADERS
    }).catch(() => {})
  }

  // Move claim from staging -> pending (for further editing)
  const unstageClaim = (claimId) => {
    const claim = stagedClaims.find(c => c.id === claimId)
    if (!claim) return
    setPendingClaims(prev => [...prev, { ...claim }].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)))
    setStagedClaims(prev => prev.filter(c => c.id !== claimId))
  }

  const saveDiscardedToBackend = async (claims) => {
    if (!claims.length) return []
    try {
      const resp = await fetch(`${BACKEND_URL}/api/discard-claims`, {
        method: 'POST',
        headers: FETCH_HEADERS,
        body: JSON.stringify({
          claims: claims.map(c => ({ name: c.name, claim: c.claim })),
          episode_key: episodeKey
        })
      })
      if (!resp.ok) return []
      const data = await resp.json()
      return data.ids || []
    } catch {
      return []
    }
  }

  // Move claim from pending -> discarded
  const discardClaim = async (claimId) => {
    const claim = pendingClaims.find(c => c.id === claimId)
    if (!claim) return
    // Optimistically move to discarded (no dbId yet)
    setDiscardedClaims(prev => [...prev, { ...claim }])
    setPendingClaims(prev => prev.filter(c => c.id !== claimId))
    // Persist to DB and attach the returned ID so undiscard can delete it
    const ids = await saveDiscardedToBackend([claim])
    if (ids[0]) {
      setDiscardedClaims(prev => prev.map(c =>
        c.id === claimId ? { ...c, dbId: ids[0] } : c
      ))
    }
    // Optimistically update pendingBlocks; dismiss from backend if block is now empty
    setPendingBlocks(prev => {
      const updated = prev
        .map(block => ({ ...block, claims: block.claims.filter(c => c.id !== claimId) }))
        .filter(block => block.claims.length > 0)
      const emptiedBlock = prev.find(block =>
        block.claims.some(c => c.id === claimId) &&
        block.claims.length === 1
      )
      if (emptiedBlock) dismissBlock(emptiedBlock.blockId)
      return updated
    })
    setLocalEdits(prev => {
      const { [claimId]: _, ...rest } = prev
      return rest
    })
  }

  // Move claim from discarded -> pending
  const undiscardClaim = (claimId) => {
    const claim = discardedClaims.find(c => c.id === claimId)
    if (!claim) return
    // Determine DB row id: explicit dbId or encoded in 'discarded_N' format
    const dbId = claim.dbId ||
      (claimId.startsWith('discarded_') ? parseInt(claimId.replace('discarded_', ''), 10) : null)
    if (dbId) {
      fetch(`${BACKEND_URL}/api/fact-checks/${dbId}`, {
        method: 'DELETE',
        headers: FETCH_HEADERS
      }).catch(() => {})
    }
    setPendingClaims(prev => [...prev, { ...claim }].sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp)))
    setDiscardedClaims(prev => prev.filter(c => c.id !== claimId))
  }

  // Discard all claims in a collection (block)
  const discardCollection = async (blockId) => {
    const claimsToDiscard = pendingClaims.filter(c => c.blockId === blockId && !c.resendOf)
    // Optimistically move to discarded
    setDiscardedClaims(prev => [...prev, ...claimsToDiscard])
    setPendingClaims(prev => prev.filter(c => c.blockId !== blockId || c.resendOf))
    setPendingBlocks(prev => prev.filter(block => block.blockId !== blockId))
    dismissBlock(blockId)
    setLocalEdits(prev => {
      const next = { ...prev }
      claimsToDiscard.forEach(c => delete next[c.id])
      return next
    })
    // Persist and attach returned IDs
    const ids = await saveDiscardedToBackend(claimsToDiscard)
    if (ids.length) {
      const idMap = Object.fromEntries(claimsToDiscard.map((c, i) => [c.id, ids[i]]))
      setDiscardedClaims(prev => prev.map(c =>
        idMap[c.id] ? { ...c, dbId: idMap[c.id] } : c
      ))
    }
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
      alert('Keine Claims zum Senden ausgewählt!')
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
          headers: FETCH_HEADERS,
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
      await Promise.all(resendClaims.map(async (claim) => {
        const response = await fetch(`${BACKEND_URL}/api/fact-checks/resend`, {
          method: 'POST',
          headers: FETCH_HEADERS,
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
      }))
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

      // Dismiss source blocks from backend (best-effort cleanup)
      const blockIds = [...new Set(stagedClaims.map(c => c.blockId).filter(Boolean))]
      blockIds.forEach(dismissBlock)

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
  const groupedBySpeaker = useMemo(() => speakers.reduce((acc, speaker) => {
    acc[speaker] = factChecks.filter(fc => {
      const factCheckSpeaker = fc.sprecher || ''
      // Exact match
      if (factCheckSpeaker === speaker) return true
      // Partial match: if config speaker contains fact-check speaker or vice versa
      if (speaker.includes(factCheckSpeaker) || factCheckSpeaker.includes(speaker)) return true
      return false
    })
    return acc
  }, {}), [speakers, factChecks])

  return (
    <>
      <header className="app-header">
        <div className="factcheck-header-content">
          <div>
            <h1>Fakten-Check - {displayTitle}</h1>
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
            pipelineEvents={pipelineEvents}
            onStage={stageClaimForSending}
            onUnstage={unstageClaim}
            onDiscard={discardClaim}
            onUndiscard={undiscardClaim}
            onDiscardCollection={discardCollection}
            onUpdatePending={updatePendingClaim}
            onSendAll={sendStagedClaims}
            onResend={prepareResend}
            onRetrigger={retriggerBlock}
          />
        ) : (
          <>
            <BackendErrorDisplay error={backendError} />
            <SpeakerColumns
              speakers={speakers}
              groupedBySpeaker={groupedBySpeaker}
              onSelect={setSelectedClaim}
            />
            {selectedClaim && (
              <ClaimDetailOverlay
                claim={selectedClaim}
                onClose={() => setSelectedClaim(null)}
              />
            )}
          </>
        )}
      </main>
    </>
  )
}
