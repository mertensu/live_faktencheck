/**
 * API service for backend communication
 */

export const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || 'http://localhost:5000'

// N8N Webhook URL for verified claims
export const N8N_VERIFIED_WEBHOOK = import.meta.env.VITE_N8N_WEBHOOK_URL || "http://localhost:5678/webhook/verified-claims"

// Debug logging - only active in development
export const debug = {
  log: (...args) => { if (import.meta.env.DEV) console.log(...args) },
  warn: (...args) => { if (import.meta.env.DEV) console.warn(...args) },
  error: (...args) => { if (import.meta.env.DEV) console.error(...args) }
}

export const FETCH_HEADERS = {
  'Accept': 'application/json',
  'Content-Type': 'application/json'
}

// Access code (Phase 3a gate) — persisted in localStorage, sent as X-Access-Code.
const ACCESS_CODE_KEY = 'fc_access_code'

export const getAccessCode = () => {
  try { return localStorage.getItem(ACCESS_CODE_KEY) || '' } catch { return '' }
}

export const setAccessCode = (code) => {
  try {
    if (code) localStorage.setItem(ACCESS_CODE_KEY, code)
    else localStorage.removeItem(ACCESS_CODE_KEY)
  } catch { /* ignore storage errors */ }
}

// Headers including the access code when present. Harmless on open GET endpoints,
// required on gated POST/PUT endpoints.
export const authHeaders = () => {
  const code = getAccessCode()
  return code ? { ...FETCH_HEADERS, 'X-Access-Code': code } : { ...FETCH_HEADERS }
}

const isJsonResponse = (response) => {
  const contentType = response.headers.get('content-type')
  return contentType && contentType.includes('application/json')
}

// Helper: Safe JSON parsing with error handling
export const safeJsonParse = async (response, errorContext = '') => {
  const text = await response.text()
  if (!isJsonResponse(response) && (text.trim().startsWith('<!DOCTYPE') || text.includes('<html'))) {
    debug.error(`${errorContext}: Backend responds with HTML instead of JSON`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Status: ${response.status}`)
    debug.error(`   Response (first 200 chars): ${text.substring(0, 200)}`)
    throw new Error('Backend responds with HTML instead of JSON. Check if backend is running.')
  }
  try {
    return JSON.parse(text)
  } catch (error) {
    debug.error(`${errorContext}: Error parsing JSON response`)
    debug.error(`   URL: ${response.url}`)
    debug.error(`   Error: ${error.message}`)
    throw error
  }
}

export async function createSession(payload) {
  const res = await fetch(`${BACKEND_URL}/api/sessions`, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify(payload),
  })
  const data = await safeJsonParse(res, 'createSession')
  if (!res.ok) {
    throw new Error(data?.detail || `createSession failed (${res.status})`)
  }
  return data
}

export async function endSession(sessionId) {
  const res = await fetch(`${BACKEND_URL}/api/sessions/${sessionId}/end`, {
    method: 'POST', headers: authHeaders(),
  })
  const data = await safeJsonParse(res, 'endSession')
  if (!res.ok) {
    throw new Error(data?.detail || `endSession failed (${res.status})`)
  }
  return data
}

// Submit a single claim for a one-shot fact-check (Phase Q).
export async function submitQuickCheck(claim) {
  const res = await fetch(`${BACKEND_URL}/api/quick-check`, {
    method: 'POST', headers: authHeaders(), body: JSON.stringify({ claim }),
  })
  const data = await safeJsonParse(res, 'submitQuickCheck')
  if (!res.ok) {
    throw new Error(data?.detail || `submitQuickCheck failed (${res.status})`)
  }
  return data  // { fact_check, limit, remaining }
}

// Load this code's past quick checks (open GET, keyed by quick-<code>).
export async function fetchQuickCheckHistory() {
  const code = getAccessCode()
  if (!code) return []
  const res = await fetch(`${BACKEND_URL}/api/fact-checks?session_id=quick-${encodeURIComponent(code)}`, {
    headers: authHeaders(),
  })
  if (!res.ok) return []
  return safeJsonParse(res, 'fetchQuickCheckHistory')
}

// Cheaply validate an access code without storing it (Phase 1b homepage unlock).
// Returns { name, quick_check_limit, quick_checks_used } or throws on non-ok.
export async function validateCode(code) {
  const res = await fetch(`${BACKEND_URL}/api/validate-code`, {
    headers: { ...FETCH_HEADERS, 'X-Access-Code': code },
  })
  const data = await safeJsonParse(res, 'validateCode')
  if (!res.ok) {
    throw new Error(data?.detail || `validateCode failed (${res.status})`)
  }
  return data
}
